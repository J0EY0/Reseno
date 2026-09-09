import sys
import warnings
from getpass import GetPassWarning, getpass

import httpx

from app.schemas.auth import AuthSetupStatusResponse


def main() -> int:
    """Create the owner through the running container's local setup endpoint."""

    try:
        with httpx.Client(
            base_url="http://127.0.0.1:8000",
            timeout=10.0,
            trust_env=False,
        ) as client:
            response = client.get("/api/auth/setup")
            response.raise_for_status()
            setup = AuthSetupStatusResponse.model_validate(response.json()["data"])
            if not setup.setup_required:
                print("The owner is already configured. Sign in through the browser.")
                return 0

            print("Username: at least 3 letters, digits, underscores or hyphens.")
            print("Password: at least 8 characters, including a letter and a digit.")
            username = input("Username: ")
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                password = getpass("Password: ")
                confirmation = getpass("Confirm password: ")
            response = client.post(
                "/api/auth/setup",
                json={
                    "username": username,
                    "password": password,
                    "confirmPassword": confirmation,
                },
            )
            response.raise_for_status()
    except (KeyboardInterrupt, EOFError):
        print("\nOwner setup cancelled.", file=sys.stderr)
        return 1
    except GetPassWarning:
        print(
            "Owner setup requires a terminal with hidden password input.",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPStatusError as exc:
        print(
            f"Owner setup failed (HTTP {exc.response.status_code}). "
            "Check the credentials and try again.",
            file=sys.stderr,
        )
        return 1
    except httpx.RequestError:
        print(
            "Cannot reach Reseno. Check that the container is running.",
            file=sys.stderr,
        )
        return 1
    except (KeyError, TypeError, ValueError):
        print("Reseno returned an invalid setup response.", file=sys.stderr)
        return 1

    print("Owner created. Open Reseno in your browser and sign in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
