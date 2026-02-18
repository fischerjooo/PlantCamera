from plantcamera.services.updater import select_update_branch


def test_select_update_branch_prefers_current_when_remote_exists():
    assert select_update_branch("feature", "main", ["dev"], True) == "feature"


def test_select_update_branch_falls_back_to_main_when_current_has_no_remote():
    assert select_update_branch("feature", "main", ["dev"], False) == "main"


def test_select_update_branch_uses_candidate_from_main():
    assert select_update_branch("main", "main", ["dev", "feat"], True) == "dev"
