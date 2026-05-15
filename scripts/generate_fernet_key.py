from __future__ import annotations


def main() -> int:
    from cryptography.fernet import Fernet

    print(Fernet.generate_key().decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
