import multiprocessing

from imgswitch import history


def test_record_list_get_delete(config_file, tmp_path):
    kept = tmp_path / "kept.png"
    kept.write_bytes(b"png")
    first = history.record({"source": "claude", "backend": "unsloth", "prompt": "a fox", "outputs": [str(kept)]})
    second = history.record({"source": "playground", "backend": "a1111", "prompt": "a bird",
                             "outputs": [str(tmp_path / "gone.png")]})

    items, total = history.list_entries()
    assert total == 2 and [i["id"] for i in items] == [second["id"], first["id"]]  # newest first
    assert items[0]["missing"] == [True] and items[1]["missing"] == [False]
    assert history.list_entries(query="FOX")[0][0]["id"] == first["id"]
    assert history.list_entries(source="playground")[1] == 1
    assert history.list_entries(backend="unsloth")[1] == 1
    assert history.get(first["id"])["prompt"] == "a fox"

    assert history.delete(first["id"]) and not history.delete(first["id"])
    assert history.list_entries()[1] == 1
    assert kept.exists()  # removing an entry never deletes the image
    assert history.clear() == 1 and history.list_entries()[1] == 0


def test_bad_lines_are_skipped(config_file):
    history.record({"prompt": "ok"})
    with history.history_path().open("a") as f:
        f.write('{"truncated": \n')
    history.record({"prompt": "also ok"})
    assert [i["prompt"] for i in history.list_entries()[0]] == ["also ok", "ok"]


def _append_many(n: int) -> None:
    for i in range(n):
        history.record({"prompt": "x" * 2000, "i": i})  # long lines make torn writes likely without the lock


def test_concurrent_appends_from_several_processes(config_file):
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_append_many, args=(25,)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert history.list_entries(limit=500)[1] == 100
