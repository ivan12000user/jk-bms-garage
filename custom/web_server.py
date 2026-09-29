#!/usr/bin/env python3

import copy
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from http.server import (
    ThreadingHTTPServer,
    SimpleHTTPRequestHandler,
)
from pathlib import Path
from urllib.parse import urlsplit

import paho.mqtt.client as mqtt


WEB_DIR = Path("/opt/batmon-ha/web")
OPTIONS = Path("/opt/batmon-ha/options.json")
STATE_FILE = WEB_DIR / "state.json"
HISTORY_FILE = WEB_DIR / "jk_log.csv"
BACKUP_DIR = Path("/opt/batmon-ha/config-backups")

LISTEN = "0.0.0.0"
PORT = 8088

APPLY_LOCK = threading.Lock()
MQTT_STATUS_LOCK = threading.Lock()

mqtt_status_cache = {
    "timestamp": 0,
    "ok": False,
    "message": "не проверялся",
}


def load_options():
    with OPTIONS.open(
        encoding="utf-8"
    ) as f:
        return json.load(f)


def safe_config(c):
    devices = c.get("devices") or []
    dev = devices[0] if devices else {}

    return {
        "mqtt_broker":
            c.get("mqtt_broker", ""),

        "mqtt_port":
            int(c.get("mqtt_port", 1883)),

        "mqtt_user":
            c.get("mqtt_user", ""),

        "mqtt_password_set":
            bool(c.get("mqtt_password")),

        "mqtt_prefix":
            dev.get("alias", ""),

        "sample_period":
            float(c.get("sample_period", 20)),

        "publish_period":
            float(c.get("publish_period", 20)),

        "invert_current":
            bool(c.get("invert_current", False)),

        "keep_alive":
            bool(c.get("keep_alive", False)),

        "adapter":
            dev.get("adapter"),

        "bms_type":
            dev.get("type"),
    }


def validate_payload(payload, base):
    c = copy.deepcopy(base)

    broker = str(
        payload.get(
            "mqtt_broker",
            c.get("mqtt_broker", "")
        )
    ).strip()

    if not broker:
        raise ValueError(
            "MQTT broker не задан"
        )

    if (
        "://" in broker
        or "/" in broker
        or " " in broker
    ):
        raise ValueError(
            "MQTT broker должен быть IP "
            "или DNS-именем без протокола"
        )

    if len(broker) > 253:
        raise ValueError(
            "Слишком длинное имя MQTT broker"
        )

    try:
        port = int(
            payload.get(
                "mqtt_port",
                c.get("mqtt_port", 1883)
            )
        )
    except Exception:
        raise ValueError(
            "Некорректный MQTT port"
        )

    if not 1 <= port <= 65535:
        raise ValueError(
            "MQTT port должен быть 1..65535"
        )

    user = str(
        payload.get(
            "mqtt_user",
            c.get("mqtt_user", "")
        )
    ).strip()

    if len(user) > 128:
        raise ValueError(
            "Слишком длинный MQTT user"
        )

    try:
        sample = float(
            payload.get(
                "sample_period",
                c.get("sample_period", 20)
            )
        )

        publish = float(
            payload.get(
                "publish_period",
                c.get("publish_period", 20)
            )
        )

    except Exception:
        raise ValueError(
            "Некорректный период"
        )

    if not 2 <= sample <= 3600:
        raise ValueError(
            "Период опроса: 2..3600 с"
        )

    if not 2 <= publish <= 3600:
        raise ValueError(
            "Период MQTT: 2..3600 с"
        )

    if publish < sample:
        raise ValueError(
            "Период публикации MQTT "
            "не должен быть меньше периода опроса"
        )

    c["mqtt_broker"] = broker
    c["mqtt_port"] = port
    c["mqtt_user"] = user

    password = payload.get(
        "mqtt_password",
        None
    )

    if password is not None:
        password = str(password)

        # Пустое поле = оставить существующий пароль.
        if password:
            if len(password) > 512:
                raise ValueError(
                    "MQTT password слишком длинный"
                )

            c["mqtt_password"] = password

    if payload.get(
        "clear_mqtt_password",
        False
    ):
        c["mqtt_password"] = ""

    c["sample_period"] = sample
    c["publish_period"] = publish

    c["invert_current"] = bool(
        payload.get(
            "invert_current",
            c.get("invert_current", False)
        )
    )

    c["keep_alive"] = bool(
        payload.get(
            "keep_alive",
            c.get("keep_alive", False)
        )
    )

    return c


def mqtt_test(c, timeout=6):
    host = c.get("mqtt_broker")
    port = int(c.get("mqtt_port", 1883))

    result = {
        "ok": False,
        "message": "timeout",
    }

    done = threading.Event()

    def on_connect(
        client,
        userdata,
        flags,
        reason_code,
        properties
    ):
        failure = getattr(
            reason_code,
            "is_failure",
            None
        )

        if failure is None:
            try:
                ok = int(reason_code) == 0
            except Exception:
                ok = str(reason_code).lower() in (
                    "success",
                    "0",
                )
        else:
            ok = not failure

        result["ok"] = ok
        result["message"] = str(
            reason_code
        )

        done.set()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=(
            "jk-web-test-"
            + str(os.getpid())
            + "-"
            + str(int(time.time()))
        )
    )

    client.on_connect = on_connect

    if c.get("mqtt_user"):
        client.username_pw_set(
            c.get("mqtt_user"),
            c.get("mqtt_password", "")
        )

    try:
        client.connect_async(
            host,
            port,
            keepalive=10
        )

        client.loop_start()

        if not done.wait(timeout):
            result = {
                "ok": False,
                "message":
                    "нет ответа от MQTT broker",
            }

    except Exception as e:
        result = {
            "ok": False,
            "message": str(e),
        }

    finally:
        try:
            client.disconnect()
        except Exception:
            pass

        try:
            client.loop_stop()
        except Exception:
            pass

    return result


def service_active(name):
    return subprocess.run(
        [
            "systemctl",
            "is-active",
            "--quiet",
            name,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def read_state_timestamp():
    try:
        with STATE_FILE.open(
            encoding="utf-8"
        ) as f:
            s = json.load(f)

        return float(
            s.get("timestamp", 0)
        )

    except Exception:
        return 0


def atomic_write_options(c):
    OPTIONS.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fd, tmp_name = tempfile.mkstemp(
        prefix=".options.",
        suffix=".json.tmp",
        dir=str(OPTIONS.parent)
    )

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                c,
                f,
                ensure_ascii=False,
                indent=2
            )

            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.chmod(
            tmp_name,
            0o600
        )

        os.replace(
            tmp_name,
            OPTIONS
        )

    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def rollback(backup):
    shutil.copy2(
        backup,
        OPTIONS
    )

    os.chmod(
        OPTIONS,
        0o600
    )

    subprocess.run(
        [
            "systemctl",
            "restart",
            "batmon-jk-bms.service",
        ],
        timeout=30
    )


def apply_config(new_config):
    with APPLY_LOCK:

        mqtt_result = mqtt_test(
            new_config
        )

        if not mqtt_result["ok"]:
            return {
                "ok": False,
                "stage": "mqtt_test",
                "message":
                    "MQTT проверка не пройдена: "
                    + mqtt_result["message"],
            }

        BACKUP_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        stamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        backup = (
            BACKUP_DIR
            / f"options.json.{stamp}.bak"
        )

        shutil.copy2(
            OPTIONS,
            backup
        )

        old_ts = read_state_timestamp()

        try:
            atomic_write_options(
                new_config
            )

            r = subprocess.run(
                [
                    "systemctl",
                    "restart",
                    "batmon-jk-bms.service",
                ],
                timeout=30,
                capture_output=True,
                text=True
            )

            if r.returncode != 0:
                raise RuntimeError(
                    "systemctl restart: "
                    + (
                        r.stderr.strip()
                        or r.stdout.strip()
                    )
                )

            wait_seconds = min(
                max(
                    float(
                        new_config.get(
                            "sample_period",
                            20
                        )
                    ) * 2 + 15,
                    35
                ),
                90
            )

            deadline = (
                time.time()
                + wait_seconds
            )

            while time.time() < deadline:

                if not service_active(
                    "batmon-jk-bms.service"
                ):
                    raise RuntimeError(
                        "BatMON service stopped"
                    )

                new_ts = (
                    read_state_timestamp()
                )

                if new_ts > old_ts:
                    return {
                        "ok": True,
                        "message":
                            "Настройки применены, "
                            "BatMON получает новые данные",

                        "backup":
                            str(backup),

                        "mqtt":
                            mqtt_result,
                    }

                time.sleep(2)

            raise RuntimeError(
                "после перезапуска не появились "
                "новые данные JK BMS"
            )

        except Exception as e:

            try:
                rollback(
                    backup
                )

                rollback_msg = (
                    "Предыдущий options.json "
                    "восстановлен"
                )

            except Exception as re:
                rollback_msg = (
                    "ОШИБКА rollback: "
                    + str(re)
                )

            return {
                "ok": False,
                "stage": "restart",
                "message":
                    str(e)
                    + ". "
                    + rollback_msg,

                "backup":
                    str(backup),
            }


def cached_mqtt_status():
    global mqtt_status_cache

    with MQTT_STATUS_LOCK:

        now = time.time()

        if (
            now
            - mqtt_status_cache["timestamp"]
            < 30
        ):
            return dict(
                mqtt_status_cache
            )

        try:
            c = load_options()
            r = mqtt_test(c)

        except Exception as e:
            r = {
                "ok": False,
                "message": str(e),
            }

        mqtt_status_cache = {
            "timestamp": now,
            "ok": r["ok"],
            "message": r["message"],
        }

        return dict(
            mqtt_status_cache
        )


def current_status():
    state_ts = read_state_timestamp()

    age = (
        time.time() - state_ts
        if state_ts
        else None
    )

    mqtt_state = (
        cached_mqtt_status()
    )

    return {
        "batmon_active":
            service_active(
                "batmon-jk-bms.service"
            ),

        "state_age_sec":
            round(age, 1)
            if age is not None
            else None,

        "state_fresh":
            age is not None
            and age < 90,

        "mqtt_ok":
            mqtt_state["ok"],

        "mqtt_message":
            mqtt_state["message"],
    }


class Handler(SimpleHTTPRequestHandler):

    def send_json(
        self,
        data,
        status=200
    ):
        body = json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Cache-Control",
            "no-store"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def read_json(self):
        try:
            size = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )
        except Exception:
            size = 0

        if (
            size <= 0
            or size > 16384
        ):
            raise ValueError(
                "Некорректный размер запроса"
            )

        raw = self.rfile.read(size)

        return json.loads(
            raw.decode("utf-8")
        )

    def do_GET(self):
        path = urlsplit(
            self.path
        ).path

        if path == "/api/config":
            try:
                self.send_json(
                    safe_config(
                        load_options()
                    )
                )
            except Exception as e:
                self.send_json(
                    {
                        "error": str(e)
                    },
                    500
                )

            return

        if path == "/api/history.csv":
            if not HISTORY_FILE.exists():
                self.send_json(
                    {
                        "ok": False,
                        "message": "CSV history not found"
                    },
                    404
                )
                return

            data = HISTORY_FILE.read_bytes()

            filename = (
                "jk-bms-garage-72h-"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".csv"
            )

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/csv; charset=utf-8"
            )

            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.send_header(
                "Content-Length",
                str(len(data))
            )

            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/api/status":
            self.send_json(
                current_status()
            )
            return

        super().do_GET()

    def do_POST(self):
        path = urlsplit(
            self.path
        ).path

        # Не даём чужой web-странице сделать
        # простой CSRF-запрос к настройкам.
        if (
            self.headers.get(
                "X-JK-Config"
            )
            != "1"
        ):
            self.send_json(
                {
                    "ok": False,
                    "message":
                        "Missing X-JK-Config header"
                },
                403
            )
            return

        try:
            payload = self.read_json()

            current = load_options()

            candidate = validate_payload(
                payload,
                current
            )

        except Exception as e:
            self.send_json(
                {
                    "ok": False,
                    "message": str(e)
                },
                400
            )
            return

        if path == "/api/mqtt/test":

            result = mqtt_test(
                candidate
            )

            self.send_json(
                {
                    "ok": result["ok"],
                    "message":
                        result["message"]
                },
                200 if result["ok"] else 400
            )

            return

        if path == "/api/config":

            result = apply_config(
                candidate
            )

            self.send_json(
                result,
                200 if result["ok"] else 500
            )

            return

        self.send_json(
            {
                "ok": False,
                "message": "Not found"
            },
            404
        )

    def end_headers(self):
        if (
            self.path.startswith(
                "/state.json"
            )
            or self.path.startswith(
                "/jk_log.csv"
            )
            or self.path.startswith(
                "/api/"
            )
        ):
            self.send_header(
                "Cache-Control",
                "no-store, no-cache, must-revalidate"
            )

        super().end_headers()

    def log_message(
        self,
        fmt,
        *args
    ):
        # Не засорять journal запросами
        # state.json каждые несколько секунд.
        pass


os.chdir(WEB_DIR)

server = ThreadingHTTPServer(
    (LISTEN, PORT),
    Handler,
)

print(
    f"JK web: http://{LISTEN}:{PORT}/ "
    f"directory={WEB_DIR}",
    flush=True,
)

server.serve_forever()
