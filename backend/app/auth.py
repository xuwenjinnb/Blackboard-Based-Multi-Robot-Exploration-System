from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

import redis


ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_ANALYST = "analyst"
MANAGED_ROLES = {ROLE_OPERATOR, ROLE_ANALYST}
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


def now_ms() -> int:
    return int(time.time() * 1000)


class AuthStore:
    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self.redis = client
        self.prefix = prefix.rstrip(":")
        self.ensure_super_admin()

    def key(self, name: str) -> str:
        return f"{self.prefix}:auth:{name}"

    @staticmethod
    def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            210_000,
        ).hex()
        return salt, digest

    @classmethod
    def verify_password(cls, password: str, salt: str, expected: str) -> bool:
        _, actual = cls.hash_password(password, salt)
        return hmac.compare_digest(actual, expected)

    def ensure_default_user(
        self,
        username: str,
        password: str,
        role: str,
        display_name: str,
    ) -> None:
        if self.redis.hexists(self.key("users"), username):
            return
        salt, password_hash = self.hash_password(password)
        timestamp = now_ms()
        user = {
            "username": username,
            "displayName": display_name,
            "role": role,
            "enabled": True,
            "salt": salt,
            "passwordHash": password_hash,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        self.redis.hset(self.key("users"), username, json.dumps(user, ensure_ascii=False))

    def ensure_super_admin(self) -> None:
        self.ensure_default_user("huadian", "123456", ROLE_ADMIN, "超级管理员")
        self.ensure_default_user("operator", "123456", ROLE_OPERATOR, "系统运行员")
        self.ensure_default_user("analyst", "123456", ROLE_ANALYST, "分析员")

    def _load_user(self, username: str) -> dict[str, Any] | None:
        raw = self.redis.hget(self.key("users"), username)
        return json.loads(raw) if raw else None

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in user.items()
            if key not in {"salt", "passwordHash"}
        }
        public.setdefault("enabled", True)
        return public

    def login(self, username: str, password: str) -> dict[str, Any] | None:
        user = self._load_user(username.strip())
        if (
            not user
            or not user.get("enabled", True)
            or not self.verify_password(password, user["salt"], user["passwordHash"])
        ):
            return None
        token = secrets.token_urlsafe(32)
        session = {
            "username": user["username"],
            "createdAt": now_ms(),
        }
        self.redis.setex(self.key(f"session:{token}"), 12 * 60 * 60, json.dumps(session))
        return {"token": token, "user": self.public_user(user)}

    def get_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        raw = self.redis.get(self.key(f"session:{token}"))
        if not raw:
            return None
        session = json.loads(raw)
        user = self._load_user(session["username"])
        if not user or not user.get("enabled", True):
            return None
        return self.public_user(user)

    def logout(self, token: str | None) -> None:
        if token:
            self.redis.delete(self.key(f"session:{token}"))

    def list_users(self) -> list[dict[str, Any]]:
        users = [
            self.public_user(json.loads(raw))
            for raw in self.redis.hvals(self.key("users"))
        ]
        return sorted(users, key=lambda item: (item["role"], item["username"]))

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        display_name: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        username = username.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("用户名只能包含字母、数字、点、下划线或短横线，长度为 1 到 40 位")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 位")
        if role not in MANAGED_ROLES:
            raise ValueError("只能创建系统运行员或分析员")
        if self.redis.hexists(self.key("users"), username):
            raise ValueError("用户名已存在")
        salt, password_hash = self.hash_password(password)
        timestamp = now_ms()
        user = {
            "username": username,
            "displayName": display_name.strip() or username,
            "role": role,
            "enabled": bool(enabled),
            "salt": salt,
            "passwordHash": password_hash,
            "createdAt": timestamp,
            "updatedAt": timestamp,
        }
        self.redis.hset(self.key("users"), username, json.dumps(user, ensure_ascii=False))
        return self.public_user(user)

    def update_user(
        self,
        username: str,
        *,
        password: str | None = None,
        role: str | None = None,
        display_name: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        user = self._load_user(username)
        if not user or user["role"] == ROLE_ADMIN:
            raise ValueError("用户不存在或不可修改")
        if role is not None:
            if role not in MANAGED_ROLES:
                raise ValueError("角色无效")
            user["role"] = role
        if password:
            if len(password) < 6:
                raise ValueError("密码至少需要 6 位")
            user["salt"], user["passwordHash"] = self.hash_password(password)
        if display_name is not None:
            user["displayName"] = display_name.strip() or username
        if enabled is not None:
            user["enabled"] = bool(enabled)
        user["updatedAt"] = now_ms()
        self.redis.hset(self.key("users"), username, json.dumps(user, ensure_ascii=False))
        return self.public_user(user)

    def delete_user(self, username: str) -> None:
        user = self._load_user(username)
        if not user or user["role"] == ROLE_ADMIN:
            raise ValueError("用户不存在或不可删除")
        self.redis.hdel(self.key("users"), username)
