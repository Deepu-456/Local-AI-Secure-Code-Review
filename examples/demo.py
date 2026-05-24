#!/usr/bin/env python3
"""Simple test file to demonstrate the code reviewer."""

import os
import sys
import hashlib


def get_password_hash(password):
    """Hash a password — WARNING: uses broken SHA-1."""
    return hashlib.sha1(password.encode()).hexdigest()


def delete_user(user_id):
    """Delete a user by ID — WARNING: no auth check."""
    os.system(f"rm -rf /var/users/{user_id}")


def load_config():
    """Load config — WARNING: eval on user input."""
    user_input = input("Enter config: ")
    return eval(user_input)  # nosec


API_KEY = "sk-live-abcdef1234567890abcdef1234567890"


def fetch_data(url):
    """Fetch data — WARNING: command injection."""
    import requests
    return requests.get(f"curl {url}")  # bug: wrong lib usage


if __name__ == "__main__":
    print(get_password_hash("password123"))
