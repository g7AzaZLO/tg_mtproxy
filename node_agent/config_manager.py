"""Управление конфигурационным файлом mtprotoproxy.

Читает и модифицирует config.py для mtprotoproxy (alexbers/mtprotoproxy),
добавляя и удаляя секреты пользователей.
"""

import logging
import os
import re
import signal
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigManager:
    """Управляет конфигом mtprotoproxy и его перезагрузкой.

    Attributes:
        _config_path: Путь к файлу config.py mtprotoproxy.
        _proxy_pid_file: Путь к PID-файлу mtprotoproxy.
    """

    def __init__(
        self,
        config_path: str = "/opt/mtprotoproxy/config.py",
        proxy_pid_file: str = "/opt/mtprotoproxy/mtprotoproxy.pid",
    ) -> None:
        """Инициализирует менеджер конфигурации.

        Args:
            config_path: Путь к config.py mtprotoproxy.
            proxy_pid_file: Путь к PID-файлу процесса mtprotoproxy.
        """
        self._config_path = Path(config_path)
        self._proxy_pid_file = Path(proxy_pid_file)

    def get_secrets(self) -> dict[str, str]:
        """Читает текущие секреты из конфига mtprotoproxy.

        Returns:
            Словарь {имя: секрет} из переменной USERS.
        """
        content = self._config_path.read_text(encoding="utf-8")
        match = re.search(r"USERS\s*=\s*\{([^}]*)\}", content, re.DOTALL)
        if not match:
            return {}

        users_block = match.group(1)
        secrets: dict[str, str] = {}
        for line in users_block.strip().split("\n"):
            line = line.strip().rstrip(",")
            if not line or line.startswith("#"):
                continue
            kv_match = re.match(r'"([^"]+)"\s*:\s*"([^"]+)"', line)
            if kv_match:
                secrets[kv_match.group(1)] = kv_match.group(2)
        return secrets

    def add_secret(self, name: str, secret: str) -> bool:
        """Добавляет секрет в конфиг mtprotoproxy.

        Args:
            name: Идентификатор пользователя (ключ в USERS).
            secret: DD-секрет.

        Returns:
            True при успехе.
        """
        secrets = self.get_secrets()
        secrets[name] = secret
        self._write_secrets(secrets)
        logger.info("Секрет добавлен: %s", name)
        return True

    def remove_secret(self, secret: str) -> bool:
        """Удаляет секрет из конфига по значению.

        Args:
            secret: DD-секрет для удаления.

        Returns:
            True если секрет найден и удалён, False если не найден.
        """
        secrets = self.get_secrets()
        name_to_remove = None
        for name, value in secrets.items():
            if value == secret:
                name_to_remove = name
                break

        if name_to_remove is None:
            logger.warning("Секрет не найден в конфиге: %s...", secret[:10])
            return False

        del secrets[name_to_remove]
        self._write_secrets(secrets)
        logger.info("Секрет удалён: %s", name_to_remove)
        return True

    def _write_secrets(self, secrets: dict[str, str]) -> None:
        """Перезаписывает блок USERS в конфиге.

        Args:
            secrets: Словарь {имя: секрет}.
        """
        content = self._config_path.read_text(encoding="utf-8")

        users_lines = []
        for name, secret in sorted(secrets.items()):
            users_lines.append(f'    "{name}": "{secret}",')
        users_block = "USERS = {\n" + "\n".join(users_lines) + "\n}"

        # Заменяем существующий блок USERS
        new_content = re.sub(
            r"USERS\s*=\s*\{[^}]*\}",
            users_block,
            content,
            flags=re.DOTALL,
        )
        self._config_path.write_text(new_content, encoding="utf-8")

    def reload_proxy(self) -> bool:
        """Отправляет SIGHUP процессу mtprotoproxy для перезагрузки конфига.

        Returns:
            True при успешной отправке сигнала, False при ошибке.
        """
        pid = self._get_proxy_pid()
        if pid is None:
            logger.error("Не удалось определить PID mtprotoproxy")
            return False

        try:
            os.kill(pid, signal.SIGHUP)
            logger.info("SIGHUP отправлен процессу mtprotoproxy (PID=%d)", pid)
            return True
        except OSError:
            logger.exception("Ошибка отправки SIGHUP процессу PID=%d", pid)
            return False

    def _get_proxy_pid(self) -> int | None:
        """Получает PID процесса mtprotoproxy.

        Сначала пробует PID-файл, затем ищет через /proc.

        Returns:
            PID процесса или None.
        """
        # Попытка 1: PID-файл
        if self._proxy_pid_file.exists():
            try:
                pid = int(self._proxy_pid_file.read_text().strip())
                # Проверяем, что процесс жив
                os.kill(pid, 0)
                return pid
            except (ValueError, OSError):
                pass

        # Попытка 2: поиск по имени процесса
        try:
            import subprocess

            result = subprocess.run(
                ["pgrep", "-f", "mtprotoproxy"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                pids = result.stdout.strip().split("\n")
                return int(pids[0])
        except (FileNotFoundError, ValueError):
            pass

        return None

    def get_stats(self) -> dict:
        """Возвращает базовую статистику.

        Returns:
            Словарь с количеством секретов и статусом процесса.
        """
        secrets = self.get_secrets()
        pid = self._get_proxy_pid()
        return {
            "secrets_count": len(secrets),
            "proxy_running": pid is not None,
            "proxy_pid": pid,
        }
