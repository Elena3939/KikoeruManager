from app.core.failure_reason_formatter import (
    format_problem_failure_message,
    infer_extract_failure_reason,
)


def test_dlsite_linkage_incomplete_is_not_extract_incomplete():
    metadata = {
        "failure_stage": "process",
        "retry_kind": "dlsite_linkage_uncertain",
        "error_message": "DLsite 关联链结果不完整，疑似翻译作品，等待重试后重新预检",
    }

    assert infer_extract_failure_reason(metadata, metadata["error_message"]) == "dlsite_linkage_uncertain"
    assert format_problem_failure_message(metadata, metadata["error_message"], stage="process") == (
        "处理暂停：DLsite 关联链不完整，尚未进入正式解压，请稍后重试或人工处理"
    )


def test_extract_incomplete_marker_still_formats_as_extract_failure():
    metadata = {"failure_stage": "extract", "error_message": "解压结果不完整"}

    assert infer_extract_failure_reason(metadata, metadata["error_message"]) == "extract_incomplete"
    assert "解压结果未通过完整性校验" in format_problem_failure_message(
        metadata,
        metadata["error_message"],
        stage="extract",
    )
