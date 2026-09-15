from ase.verifier.policy import PatchPolicy, check_patch_policy, inspect_patch


ALLOWED_PATCH = """--- a/target/fleetops/app/services/telemetry.py
+++ b/target/fleetops/app/services/telemetry.py
@@ -1,2 +1,3 @@
 old
+new
 keep
"""

FORBIDDEN_TEST_PATCH = """--- a/target/fleetops/tests/test_api.py
+++ b/target/fleetops/tests/test_api.py
@@ -1,2 +1,3 @@
 old
+new
 keep
"""

DELETE_FORBIDDEN_PATCH = """--- a/target/fleetops/tests/test_api.py
+++ /dev/null
@@ -1,1 +0,0 @@
-old
"""


def test_application_patch_passes_default_policy() -> None:
    result = check_patch_policy(ALLOWED_PATCH, PatchPolicy())

    assert result.passed is True


def test_test_file_patch_is_rejected() -> None:
    result = check_patch_policy(FORBIDDEN_TEST_PATCH, PatchPolicy())

    assert result.passed is False
    assert "forbidden path" in result.details


def test_deleted_forbidden_file_is_still_detected() -> None:
    facts = inspect_patch(DELETE_FORBIDDEN_PATCH)
    result = check_patch_policy(DELETE_FORBIDDEN_PATCH, PatchPolicy())

    assert facts.paths == ("target/fleetops/tests/test_api.py",)
    assert result.passed is False
