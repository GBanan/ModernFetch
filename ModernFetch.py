# meta developer: @GunmeN_NemnuG
# requires: psutil
# scope: heroku_min 2.0.0

import asyncio
import os
import platform
import socket
import subprocess
import time
import psutil
from herokutl.tl.types import Message
from .. import loader, utils


def _format_bytes(b: float) -> str:
    gb = b / (1024 ** 3)
    if gb >= 1.0:
        return f"{gb:.2f}ГБ"
    mb = b / (1024 ** 2)
    return f"{mb:.2f}МБ"


def _get_os_info() -> str:
    name = "Linux"
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        name = line.split("=", 1)[1].strip().strip('"')
                        break
                    elif line.startswith("NAME=") and name == "Linux":
                        name = line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
    kernel = platform.release()
    arch = platform.machine()
    return f"{name} (Ядро: {kernel}, {arch})"


def _get_uptime() -> str:
    uptime_seconds = 0.0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
    except Exception:
        uptime_seconds = max(0.0, time.time() - psutil.boot_time())

    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0 or not parts:
        parts.append(f"{minutes} мин.")
    return " ".join(parts)


def _get_cpu_info():
    model = ""
    # Check device-tree model first on ARM/Raspberry Pi
    if os.path.exists("/proc/device-tree/model"):
        try:
            with open("/proc/device-tree/model", "rb") as f:
                dt_m = f.read().decode("utf-8", errors="ignore").strip("\x00\n\r ")
                if dt_m:
                    pass
        except Exception:
            pass

    if os.path.exists("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        model = line.split(":", 1)[1].strip()
                        break
                    elif not model and ("Hardware" in line or "Processor" in line):
                        model = line.split(":", 1)[1].strip()
        except Exception:
            pass

    if not model:
        model = platform.processor() or "ARMv8 Processor"

    threads = os.cpu_count() or 1
    try:
        l1, l5, l15 = os.getloadavg()
    except Exception:
        l1 = l5 = l15 = 0.0

    load_pct = int(round((l1 / threads) * 100)) if threads else 0
    return model, threads, l1, l5, l15, load_pct


def _get_motherboard() -> str:
    # Raspberry Pi or ARM device tree
    if os.path.exists("/proc/device-tree/model"):
        try:
            with open("/proc/device-tree/model", "rb") as f:
                model = f.read().decode("utf-8", errors="ignore").strip("\x00\n\r ")
                if model:
                    return model
        except Exception:
            pass

    # Standard x86 DMI
    board_vendor, board_name = "", ""
    for path, var in [
        ("/sys/devices/virtual/dmi/id/board_vendor", "vendor"),
        ("/sys/devices/virtual/dmi/id/board_name", "name"),
        ("/sys/devices/virtual/dmi/id/product_name", "product"),
    ]:
        if os.path.exists(path):
            try:
                with open(path, "r", errors="ignore") as f:
                    val = f.read().strip()
                if var == "vendor":
                    board_vendor = val
                elif var == "name":
                    board_name = val
                elif var == "product" and not board_name:
                    board_name = val
            except Exception:
                pass

    if board_vendor and board_name:
        return f"{board_vendor} {board_name}"
    if board_name:
        return board_name
    if board_vendor:
        return board_vendor
    return "Неизвестно"


def _get_environment() -> str:
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return "Docker (контейнер)"

    try:
        with open("/proc/1/environ", "rb") as f:
            if b"container=lxc" in f.read():
                return "LXC (контейнер)"
    except Exception:
        pass

    try:
        virt = (
            subprocess.check_output(
                ["systemd-detect-virt"],
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            .decode()
            .strip()
        )
        if virt and virt != "none":
            return f"{virt.capitalize()} (виртуальный)"
    except Exception:
        pass

    for p in [
        "/sys/devices/virtual/dmi/id/product_name",
        "/sys/devices/virtual/dmi/id/sys_vendor",
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r", errors="ignore") as f:
                    v = f.read().lower()
                for known in ["kvm", "qemu", "vmware", "virtualbox", "hyper-v", "proxmox"]:
                    if known in v:
                        return f"{known.upper()} (виртуальный)"
            except Exception:
                pass

    return "Bare-metal (физический)"


def _get_ram_info():
    mem = psutil.virtual_memory()
    total = f"{mem.total / (1024 ** 3):.2f}ГБ"
    used = _format_bytes(mem.used)
    free = _format_bytes(mem.available)
    pct = round(mem.percent, 1)
    return total, used, free, pct


def _get_gpu_info() -> str:
    # Check Broadcom VideoCore (Raspberry Pi)
    if os.path.exists("/dev/vchiq") or os.path.exists("/sys/module/vc4"):
        return "Broadcom VideoCore"

    try:
        lspci = subprocess.check_output(
            ["lspci"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode()
        gpus = []
        for line in lspci.splitlines():
            if any(k in line for k in ["VGA", "3D controller", "Display controller"]):
                parts = line.split(":", 2)
                gpus.append(parts[-1].strip())
        if gpus:
            return ", ".join(gpus)
    except Exception:
        pass

    try:
        nv = (
            subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            .decode()
            .strip()
        )
        if nv:
            return nv
    except Exception:
        pass

    return "Отсутствует"


def _get_disk_info():
    model = "Неизвестно"
    raw_capacity_gb = None

    try:
        if os.path.exists("/sys/block"):
            for dev in sorted(os.listdir("/sys/block")):
                if dev.startswith(("sd", "nvme", "mmcblk", "vd")):
                    model_path = f"/sys/block/{dev}/device/model"
                    name_path = f"/sys/block/{dev}/device/name"
                    if os.path.exists(model_path):
                        with open(model_path, "r", errors="ignore") as f:
                            m = f.read().strip()
                            if m:
                                model = m
                    elif os.path.exists(name_path):
                        with open(name_path, "r", errors="ignore") as f:
                            m = f.read().strip()
                            if m:
                                model = m
                    size_path = f"/sys/block/{dev}/size"
                    if os.path.exists(size_path) and raw_capacity_gb is None:
                        sectors = int(open(size_path).read().strip())
                        raw_capacity_gb = (sectors * 512) / (1024 ** 3)
                    if model != "Неизвестно" and raw_capacity_gb is not None:
                        break
    except Exception:
        pass

    usage = psutil.disk_usage("/")
    total_gb = usage.total / (1024 ** 3)
    used_gb = usage.used / (1024 ** 3)
    free_gb = usage.free / (1024 ** 3)
    pct = round(usage.percent, 1)

    if raw_capacity_gb is None or raw_capacity_gb < total_gb:
        raw_capacity_gb = total_gb

    return model, raw_capacity_gb, total_gb, used_gb, free_gb, pct


@loader.tds
class ModernFetchMod(loader.Module):
    """Polished system info fetcher styled with custom Telegram emojis."""

    strings = {
        "name": "ModernFetch",
        "loading": '<blockquote><tg-emoji emoji-id="6037268453759389862">⏲️</tg-emoji> <strong>Сбор системной информации...</strong></blockquote>',
    }

    @loader.command()
    async def mf(self, message: Message):
        """Show polished system information"""
        await self._render(message)

    async def _render(self, message: Message):
        msg = await utils.answer(message, self.strings["loading"])

        os_info = _get_os_info()
        hostname = socket.gethostname()
        uptime = _get_uptime()
        cpu_model, threads, l1, l5, l15, load_pct = _get_cpu_info()
        mb = _get_motherboard()
        env = _get_environment()
        ram_total, ram_used, ram_free, ram_pct = _get_ram_info()
        gpu = _get_gpu_info()
        disk_model, raw_cap, total_gb, used_gb, free_gb, disk_pct = _get_disk_info()

        text = (
            "<blockquote>"
            '<tg-emoji emoji-id="5942734685976138521">🖥</tg-emoji> '
            f"<strong>ОС:</strong> {os_info}\n\n"
            '<tg-emoji emoji-id="6048723247501938454">🛜</tg-emoji> '
            f"<strong>Хостнейм:</strong> <code>{hostname}</code>\n\n"
            '<tg-emoji emoji-id="6037268453759389862">⏲️</tg-emoji> '
            f"<strong>Аптайм:</strong> {uptime}\n\n"
            '<tg-emoji emoji-id="5884428842780594914">⚡</tg-emoji> '
            f"<strong>Процессор:</strong> {cpu_model} ({threads}T)\n"
            f" ↳ <strong>Нагрузка:</strong> {l1:.2f} / {l5:.2f} / {l15:.2f} "
            f"(1/5/15 мин, ~{load_pct}% от {threads} потоков)\n\n"
            '<tg-emoji emoji-id="5962952497197748583">🔧</tg-emoji> '
            f"<strong>Материнская плата:</strong> {mb}\n"
            '<tg-emoji emoji-id="5778672437122045013">📦</tg-emoji> '
            f"<strong>Окружение:</strong> {env}\n\n"
            '<tg-emoji emoji-id="5864019342873598613">🧠</tg-emoji> '
            f"<strong>Оперативная память:</strong> {ram_total} "
            f"[Занято: {ram_used} ({ram_pct}%), Свободно: {ram_free}]\n\n"
            '<tg-emoji emoji-id="5938413566624272793">🎮</tg-emoji> '
            f"<strong>Видеокарта:</strong> {gpu}\n\n"
            '<tg-emoji emoji-id="5805506958995758422">📁</tg-emoji> '
            "<strong>Накопители:</strong>\n"
            f"   • {disk_model}\n"
            f"   ↳ <strong>Ёмкость:</strong> {raw_cap:.2f}ГБ\n"
            f"   ↳ <strong>Занято:</strong> {used_gb:.2f}ГБ из {total_gb:.2f}ГБ "
            f"({disk_pct}%), свободно {free_gb:.2f}ГБ"
            "</blockquote>"
        )

        await utils.answer(msg, text)
