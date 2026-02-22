from plantcamera.services.updater import select_update_branch


def test_select_update_branch_prefers_current_when_remote_exists():
    assert select_update_branch("feature", "main", True) == "feature"


def test_select_update_branch_falls_back_to_main_when_current_has_no_remote():
    assert select_update_branch("feature", "main", False) == "main"


def test_select_update_branch_uses_main_from_main_branch():
    assert select_update_branch("main", "main", True) == "main"


def test_select_update_branch_uses_main_from_detached_head():
    assert select_update_branch("HEAD", "main", False) == "main"
