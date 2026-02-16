"""Управление конфигурационным файлом 3proxy для SOCKS5.

Читает и модифицирует файл паролей 3proxy,
добавляя и удаляя SOCKS5-пользователей.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PASSWD_PATH = "/opt/3proxy/passwd"
DEFAULT_CONFIG_PATH = "/opt/3proxy/3proxy.cfg"


class Socks5Manager:
    """Управляет пользователями 3proxy и перезагрузкой сервиса.

    Пользователи хранятся в файле passwd в формате: ``user:CL:password``
    (CL = cleartext password).

    Attributes:
        _passwd_path: Путь к файлу паролей 3proxy.
        _config_path: Путь к конфигу 3proxy.
    """

    def __init__(
        self,
        passwd_path: str = DEFAULT_PASSWD_PATH,
        config_path: str = DEFAULT_CONFIG_PATH,
    ) -> None:
        """Инициализирует менеджер SOCKS5.

        Args:
            passwd_path: Путь к файлу паролей 3proxy.
            config_path: Путь к конфигу 3proxy.
        """
        self._passwd_path = Path(passwd_path)
        self._config_path = Path(config_path)
        self._passwd_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._passwd_path.exists():
            self._passwd_path.write_text("", encoding="utf-8")

    def get_users(self) -> dict[str, str]:
        """Читает текущих пользователей из файла паролей.

        Returns:
            Словарь {username: password}.
        """
        users: dict[str, str] = {}
        if not self._passwd_path.exists():
            return users
        for line in self._passwd_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "CL":
                users[parts[0]] = parts[2]
        return users

    def add_user(self, username: str, password: str) -> bool:
        """Добавляет SOCKS5-пользователя.

        Args:
            username: Логин.
            password: Пароль.

        Returns:
            True при успехе.
        """
        users = self.get_users()
        users[username] = password
        self._write_users(users)
        logger.info("SOCKS5 пользователь добавлен: %s", username)
        return True

    def remove_user(self, username: str) -> bool:
        """Удаляет SOCKS5-пользователя.

        Args:
            username: Логин для удаления.

        Returns:
            True если пользователь найден и удалён, False если не найден.
        """
        users = self.get_users()
        if username not in users:
            logger.warning("SOCKS5 пользователь не найден: %s", username)
            return False
        del users[username]
        self._write_users(users)
        logger.info("SOCKS5 пользователь удалён: %s", username)
        return True

    def _write_users(self, users: dict[str, str]) -> None:
        """Перезаписывает файл паролей.

        Args:
            users: Словарь {username: password}.
        """
        lines = [f"{name}:CL:{pwd}" for name, pwd in sorted(users.items())]
        self._passwd_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def reload_proxy(self) -> bool:
        """Перезапускает 3proxy через systemctl.

        Returns:
            True при успешном перезапуске.
        """
        try:
            # 3proxy не поддерживает reload — только restart
            result = subprocess.run(
                ["systemctl", "restart", "3proxy"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                logger.info("3proxy перезагружен")
                return True
            logger.error("Ошибка перезагрузки 3proxy: %s", result.stderr)
            return False
        except OSError:
            logger.exception("Ошибка вызова systemctl для 3proxy")
            return False

    def get_stats(self) -> dict:
        """Возвращает статистику SOCKS5.

        Returns:
            Словарь с количеством пользователей и статусом.
        """
        users = self.get_users()
        running = self._is_running()
        return {
            "socks5_users_count": len(users),
            "socks5_running": running,
        }

    def _is_running(self) -> bool:
        """Проверяет, запущен ли 3proxy.

        Returns:
            True если процесс работает.
        """
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "3proxy"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.strip() == "active"
        except OSError:
            return False
