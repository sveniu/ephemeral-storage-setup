import logging
import subprocess

logger = logging.getLogger(__name__)


class NonZeroExitException(Exception):
    pass


def popen(argv):
    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def simple(argv, timeout=2.0, encoding="utf-8"):
    try:
        p = popen(argv)
    except Exception as e:
        logger.error(
            "error starting subprocess",
            extra={
                "argv": argv,
                "exception": e,
            },
        )
        raise

    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        stdout, stderr = p.communicate()

    if p.returncode != 0:
        logger.error(
            "subprocess returned non-zero exit code",
            extra={
                "argv": argv,
                "rc": p.returncode,
                "stdout": stdout.decode(encoding).strip(),
                "stderr": stderr.decode(encoding).strip(),
            },
        )
        raise NonZeroExitException(f"return code: {p.returncode}")

    return stdout.decode(encoding).strip(), stderr.decode(encoding).strip()
