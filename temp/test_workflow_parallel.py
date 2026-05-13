"""Test script for workflow parallel/sequential modes."""

import sys

sys.path.insert(0, "c:\\xiangmu\\deer-flow\\backend\\packages\\harness")


def test_workflow_registration():
    """Test that all workflows are registered."""
    from deerflow.workflows import list_workflows

    workflows = list_workflows()
    print(f"Registered workflows: {workflows}")
    assert "organize" in workflows, "organize workflow not registered"
    assert "writing" in workflows, "writing workflow not registered"
    assert "post_process" in workflows, "post_process workflow not registered"
    print("[OK] All workflows registered")


def test_parallel_config():
    """Test parallel mode (default)."""
    from deerflow.config.subagents_config import get_subagents_app_config, load_subagents_config_from_dict

    # Load default config (parallel enabled)
    load_subagents_config_from_dict({})
    config = get_subagents_app_config()
    print(f"Default workflow_parallel_enabled: {config.workflow_parallel_enabled}")
    assert config.workflow_parallel_enabled == True, "Default should be parallel"
    print("[OK] Default config is parallel mode")


def test_sequential_config():
    """Test sequential mode."""
    from deerflow.config.subagents_config import get_subagents_app_config, load_subagents_config_from_dict

    # Load config with parallel disabled
    load_subagents_config_from_dict({"workflow_parallel_enabled": False})
    config = get_subagents_app_config()
    print(f"Sequential workflow_parallel_enabled: {config.workflow_parallel_enabled}")
    assert config.workflow_parallel_enabled == False, "Should be sequential"
    print("[OK] Sequential config works")


def test_organize_workflow_creation():
    """Test organize workflow creates different graphs for parallel/sequential."""
    from deerflow.workflows.novel_organize import _create_parallel_workflow, _create_sequential_workflow

    parallel_wf = _create_parallel_workflow()
    sequential_wf = _create_sequential_workflow()

    print(f"Parallel workflow type: {type(parallel_wf)}")
    print(f"Sequential workflow type: {type(sequential_wf)}")

    assert parallel_wf is not None, "Parallel workflow creation failed"
    assert sequential_wf is not None, "Sequential workflow creation failed"
    print("[OK] Both workflow variants created successfully")


def test_post_process_functions():
    """Test post process parallel/sequential functions exist.

    Note: novel_writing 的 post_process 已合并为单次 world-updater 调用，
    不再有 parallel/sequential 双实现，所以只验证 novel_post_process 这边的。
    novel_writing 改为统一通过 post_process 入口，内部直接调 _post_process_combined。
    """
    from deerflow.workflows.novel_post_process import _process_single_chapter_parallel, _process_single_chapter_sequential
    from deerflow.workflows.novel_writing import _post_process_combined, post_process

    assert callable(_process_single_chapter_parallel), "Post process parallel function not found"
    assert callable(_process_single_chapter_sequential), "Post process sequential function not found"
    assert callable(post_process), "Writing post_process entry function not found"
    assert callable(_post_process_combined), "Writing _post_process_combined function not found"
    print("[OK] All parallel/sequential functions exist")


def test_is_parallel_enabled():
    """Test _is_parallel_enabled function reads config correctly.

    Note: novel_writing 的 _is_parallel_enabled 仍保留（虽然 post_process 已合并不再使用，
    但仍可能被其它 workflow 节点引用），所以继续验证。
    """
    from deerflow.workflows.novel_organize import _is_parallel_enabled as organize_is_parallel
    from deerflow.workflows.novel_writing import _is_parallel_enabled as writing_is_parallel
    from deerflow.workflows.novel_post_process import _is_parallel_enabled as post_process_is_parallel
    from deerflow.config.subagents_config import load_subagents_config_from_dict

    # Test parallel mode
    load_subagents_config_from_dict({"workflow_parallel_enabled": True})
    assert organize_is_parallel() == True, "Organize should detect parallel"
    assert writing_is_parallel() == True, "Writing should detect parallel"
    assert post_process_is_parallel() == True, "Post-process should detect parallel"
    print("[OK] All _is_parallel_enabled detect parallel mode")

    # Test sequential mode
    load_subagents_config_from_dict({"workflow_parallel_enabled": False})
    assert organize_is_parallel() == False, "Organize should detect sequential"
    assert writing_is_parallel() == False, "Writing should detect sequential"
    assert post_process_is_parallel() == False, "Post-process should detect sequential"
    print("[OK] All _is_parallel_enabled detect sequential mode")


if __name__ == "__main__":
    print("=" * 60)
    print("Workflow Parallel/Sequential Mode Tests")
    print("=" * 60)

    test_workflow_registration()
    print()

    test_parallel_config()
    print()

    test_sequential_config()
    print()

    test_organize_workflow_creation()
    print()

    test_post_process_functions()
    print()

    test_is_parallel_enabled()
    print()

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)
