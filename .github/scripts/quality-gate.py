import json
import os
import sys


def main() -> None:
    needs = json.loads(os.environ["NEEDS_JSON"])
    event = os.environ["EVENT_NAME"]
    git_ref = os.environ["GIT_REF"]
    default_branch = os.environ["DEFAULT_BRANCH"]
    if event not in {"pull_request", "push"} or not git_ref or not default_branch:
        raise ValueError("Missing or unsupported workflow event.")
    if needs["changes"]["result"] != "success":
        raise ValueError("Change detection did not succeed.")

    outputs = needs["changes"]["outputs"]
    for name in ("run_checks", "image_inputs", "container_validation", "metadata_only"):
        if outputs[name] not in ("true", "false"):
            raise ValueError(f"Invalid change detection output: {name}.")
    run_checks = outputs["run_checks"] == "true"
    image_inputs = outputs["image_inputs"] == "true"
    container_validation = outputs["container_validation"] == "true"
    metadata_only = outputs["metadata_only"] == "true"
    if (
        (metadata_only and (run_checks or container_validation or not image_inputs))
        or (image_inputs and not (container_validation or metadata_only))
        or (container_validation and not run_checks)
    ):
        raise ValueError("Inconsistent change detection outputs.")
    if git_ref.startswith("refs/tags/") and not (
        run_checks and image_inputs and container_validation and not metadata_only
    ):
        raise ValueError("Tags require all validation inputs.")

    full_validation = (
        event == "pull_request"
        or git_ref in {"refs/heads/main", f"refs/heads/{default_branch}"}
        or git_ref.startswith("refs/tags/")
    )
    required = {
        "model-metadata": metadata_only,
        "backend": run_checks,
        "frontend": run_checks,
        "browser-smoke": run_checks and full_validation,
        "container-validation": container_validation and full_validation,
    }
    failures = []
    for job, enabled in required.items():
        expected = "success" if enabled else "skipped"
        result = needs[job]["result"]
        if result != expected:
            failures.append(f"{job}: expected {expected}, got {result}")
    if failures:
        raise ValueError("; ".join(failures))
    print("All required quality checks passed.")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
