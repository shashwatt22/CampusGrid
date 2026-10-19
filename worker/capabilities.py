import os


def get_capabilities(max_tasks=1):
    cores = os.cpu_count() or 1
    ram_mb = 4096
    try:
        import psutil
        ram_mb = int(psutil.virtual_memory().available / (1024 * 1024))
    except ImportError:
        if hasattr(os, "sysconf"):
            try:
                pages = os.sysconf("SC_AVPHYS_PAGES") if "SC_AVPHYS_PAGES" in os.sysconf_names else os.sysconf("SC_PHYS_PAGES")
                ram_mb = int(os.sysconf("SC_PAGE_SIZE") * pages / (1024 * 1024))
            except (ValueError, OSError):
                pass
    return {"cores": cores, "ram_mb": ram_mb, "max_tasks": max_tasks}
