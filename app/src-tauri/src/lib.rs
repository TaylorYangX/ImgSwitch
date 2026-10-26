//! ImgSwitch desktop shell: starts the Python backend (`main.py --gui --app`), shows the UI that talks
//! to it, and stops it again when the app exits. All image logic stays in Python, which Claude Code
//! also runs as the MCP server.

use std::fs::File;
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);

/// The backend process and, once known, where it listens or why it couldn't start.
#[derive(Default)]
struct Backend {
    outcome: Mutex<Option<Result<String, String>>>,
    settled: Condvar,
    child: Mutex<Option<Child>>,
}

impl Backend {
    fn settle(&self, outcome: Result<String, String>) {
        *self.outcome.lock().unwrap() = Some(outcome);
        self.settled.notify_all();
    }

    fn wait(&self) -> Result<String, String> {
        let mut outcome = self.outcome.lock().unwrap();
        while outcome.is_none() {
            outcome = self.settled.wait(outcome).unwrap();
        }
        outcome.clone().unwrap()
    }

    fn stop(&self) {
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// The ImgSwitch checkout this app belongs to: $IMGSWITCH_HOME, else the folder it was built from.
fn project_root() -> PathBuf {
    std::env::var_os("IMGSWITCH_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../.."))
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")))
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?.local_addr()?.port())
}

fn log_tail(path: &Path, lines: usize) -> String {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let all: Vec<&str> = text.lines().collect();
    all[all.len().saturating_sub(lines)..].join("\n")
}

/// Spawn the backend and report (through `backend`) once it accepts connections or has failed.
fn start_backend(backend: Arc<Backend>) {
    let root = project_root();
    let python = root.join(".venv/bin/python");
    let log_path = root.join("app-backend.log");
    if !python.exists() {
        backend.settle(Err(format!(
            "Python environment not found at {}.\nRun `uv sync` in {} first.",
            python.display(),
            root.display()
        )));
        return;
    }
    let spawned = (|| -> std::io::Result<(Child, u16)> {
        let port = free_port()?;
        let log = File::create(&log_path)?;
        let child = Command::new(&python)
            .arg(root.join("main.py"))
            .args(["--gui", "--app", "--port", &port.to_string()])
            .current_dir(&root)
            .stdin(Stdio::null())
            .stdout(log.try_clone()?)
            .stderr(log)
            .spawn()?;
        Ok((child, port))
    })();
    let port = match spawned {
        Ok((child, port)) => {
            *backend.child.lock().unwrap() = Some(child);
            port
        }
        Err(e) => return backend.settle(Err(format!("Could not start {}: {e}", python.display()))),
    };

    std::thread::spawn(move || {
        let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
        let started = Instant::now();
        loop {
            if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
                return backend.settle(Ok(format!("http://127.0.0.1:{port}")));
            }
            let exited = backend.child.lock().unwrap().as_mut().and_then(|c| c.try_wait().ok().flatten());
            if let Some(status) = exited {
                return backend.settle(Err(format!(
                    "The ImgSwitch backend stopped ({status}). Last lines of {}:\n\n{}",
                    log_path.display(),
                    log_tail(&log_path, 30)
                )));
            }
            if started.elapsed() > STARTUP_TIMEOUT {
                return backend.settle(Err(format!(
                    "The ImgSwitch backend didn't start within {}s. See {}.",
                    STARTUP_TIMEOUT.as_secs(),
                    log_path.display()
                )));
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    });
}

/// Where the UI should send its API requests; waits until the backend is listening.
#[tauri::command]
async fn backend_url(backend: tauri::State<'_, Arc<Backend>>) -> Result<String, String> {
    let backend = backend.inner().clone();
    tauri::async_runtime::spawn_blocking(move || backend.wait())
        .await
        .map_err(|e| e.to_string())?
}

fn is_wsl() -> bool {
    std::fs::read_to_string("/proc/version").map(|v| v.to_lowercase().contains("microsoft")).unwrap_or(false)
}

/// Under WSL, files open in Windows (Explorer and its default apps); elsewhere through xdg-open.
fn windows_path(path: &str) -> Result<String, String> {
    let out = Command::new("wslpath").args(["-w", path]).output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

fn explorer() -> &'static str {
    // Apps started from the Start menu may not have Windows folders on their PATH.
    if Path::new("/mnt/c/Windows/explorer.exe").exists() {
        "/mnt/c/Windows/explorer.exe"
    } else {
        "explorer.exe"
    }
}

/// Show a file selected in its folder.
#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    let target = Path::new(&path);
    if !target.exists() {
        return Err(format!("{path} doesn't exist"));
    }
    if is_wsl() {
        let win = windows_path(&path)?;
        Command::new(explorer()).arg(format!("/select,{win}")).spawn().map_err(|e| e.to_string())?;
    } else {
        let dir = if target.is_dir() { target } else { target.parent().unwrap_or(target) };
        Command::new("xdg-open").arg(dir).spawn().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Open a file or folder with its default application.
#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    if !Path::new(&path).exists() {
        return Err(format!("{path} doesn't exist"));
    }
    if is_wsl() {
        Command::new(explorer()).arg(windows_path(&path)?).spawn().map_err(|e| e.to_string())?;
    } else {
        Command::new("xdg-open").arg(&path).spawn().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = Arc::new(Backend::default());
    let app = tauri::Builder::default()
        // A second launch (e.g. from the Start menu) brings the open window forward instead.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(backend.clone())
        .setup({
            let backend = backend.clone();
            move |_app| {
                start_backend(backend);
                Ok(())
            }
        })
        .invoke_handler(tauri::generate_handler![backend_url, reveal_path, open_path])
        .build(tauri::generate_context!())
        .expect("error while building the ImgSwitch app");

    app.run(move |_handle, event| {
        if let RunEvent::Exit = event {
            backend.stop();
        }
    });
}
