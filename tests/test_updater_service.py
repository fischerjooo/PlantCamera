from plantcamera.services.updater import parse_candidate_branches, select_update_branch


def test_parse_candidate_branches_ignores_main_head_and_remote_alias():
    remote_raw = "\n".join([
        "origin/HEAD",
        "origin/main",
        "origin/dev",
        "origin/feature/a",
        "origin",
    ])
    assert parse_candidate_branches(remote_raw, "origin", "main") == ["dev", "feature/a"]


def test_select_update_branch_prefers_current_when_remote_exists():
    assert select_update_branch("feature", "main", ["dev"], True) == "feature"


def test_select_update_branch_falls_back_to_main_when_current_has_no_remote():
    assert select_update_branch("feature", "main", ["dev"], False) == "main"


def test_select_update_branch_uses_candidate_from_main():
    assert select_update_branch("main", "main", ["dev", "feat"], True) == "dev"


def test_select_update_branch_uses_main_from_detached_head_without_candidates():
    assert select_update_branch("HEAD", "main", [], False) == "main"
