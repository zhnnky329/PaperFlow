import hashlib
import json
import logging
import traceback
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from sqlalchemy import select
from .config import ROOT
from .db import Job, Paper, Setting, now, uid
from .html import publish_html

DEFAULTS = {
    "theme": "system",
    "font_scale": 17,
    "reader_width": 780,
    "marker_mode": "fast",
    "auto_convert_on_import": False,
}


def settings(session):
    return DEFAULTS | {row.key: row.value for row in session.scalars(select(Setting))}


def job_dict(job):
    return {c.name: getattr(job, c.name) for c in Job.__table__.columns}


class Worker:
    def __init__(self, config, sessions):
        self.config, self.sessions = config, sessions
        self.stop_event = threading.Event()
        self.process = None
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        with self.sessions() as session:
            for job in session.scalars(select(Job).where(Job.status == "running")):
                job.status, job.error_code = "failed", "INTERRUPTED"
                job.error_message = "上次转换中断，请重试。PDF 仍可阅读。"
                job.finished_at = now()
            session.commit()
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.kill(self.process)
        self.thread.join(timeout=10)

    @staticmethod
    def kill(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        except ProcessLookupError:
            pass

    def executable(self):
        return shutil.which(self.config.marker_executable)

    def enqueue(self, session, paper, force=False, attempt=1):
        from fastapi import HTTPException

        if not paper.pdf_path:
            raise HTTPException(409, "请先下载或导入 PDF")
        executable = self.executable()
        if not executable:
            raise HTTPException(503, "Marker CLI 未安装，请配置 PAPERFLOW_MARKER_EXECUTABLE")
        config = {"mode": settings(session)["marker_mode"], "output_format": "html"}
        # Include actual isolated package metadata without loading models.
        python = Path(executable).parent / "python"
        try:
            version = subprocess.run(
                [
                    str(python),
                    "-c",
                    'import importlib.metadata; print(importlib.metadata.version("marker-pdf"))',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            version = ""
        identity = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        config["marker_version"] = version or identity
        fingerprint = hashlib.sha256(
            (paper.pdf_sha256 + json.dumps(config, sort_keys=True) + identity).encode()
        ).hexdigest()
        with self.lock:
            active = session.scalar(
                select(Job).where(Job.paper_id == paper.id, Job.status.in_(["queued", "running"]))
            )
            if active:
                return active, False
            if not force:
                cached = session.scalar(
                    select(Job)
                    .where(
                        Job.paper_id == paper.id, Job.fingerprint == fingerprint, Job.status == "succeeded"
                    )
                    .order_by(Job.created_at.desc())
                )
                if cached and self.config.path(cached.result_path).is_file():
                    return cached, True
            if len(list(session.scalars(select(Job).where(Job.status.in_(["queued", "running"]))))) >= 30:
                raise HTTPException(429, "转换队列已满，请等待当前任务")
            job = Job(id=uid(), paper_id=paper.id, fingerprint=fingerprint, settings=config, attempt=attempt)
            session.add(job)
            session.commit()
            return job, False

    def cancel(self, session, job):
        with self.lock:
            if job.status in ("queued", "running"):
                job.status, job.finished_at = "canceled", now()
                session.commit()
                if self.process and self.current_job == job.id and self.process.poll() is None:
                    self.kill(self.process)

    def run(self):
        while not self.stop_event.is_set():
            with self.sessions() as session:
                job = session.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at))
                if job:
                    job_id = job.id
                    job.status, job.started_at, job.progress_stage = "running", now(), "preparing"
                    session.commit()
                else:
                    job_id = None
            if job_id:
                self.convert(job_id)
            else:
                self.stop_event.wait(0.3)

    def convert(self, job_id):
        staging = None
        phase = "preparing"
        try:
            staging = self.config.path(f"staging/{job_id}")
            staging.mkdir(parents=True, exist_ok=True)
            with self.sessions() as session:
                job = session.get(Job, job_id)
                paper = session.get(Paper, job.paper_id)
                paper_id = paper.id
                source = self.config.path(paper.pdf_path)
                argv = [
                    self.executable(),
                    str(source),
                    "--output_format",
                    "html",
                    "--output_dir",
                    str(staging / "raw"),
                    "--mode",
                    job.settings["mode"],
                ]
                phase = "converting"
                job.progress_stage = "converting"
                session.commit()
            # Diagnostics intentionally exclude raw stdout/stderr (paper text/secrets/paths).
            with (staging / "process.log").open("wb") as log:
                environment = {
                    k: v for k, v in os.environ.items() if "KEY" not in k.upper() and "TOKEN" not in k.upper()
                }
                environment.pop("SURYA_INFERENCE_URL", None)
                environment["SURYA_INFERENCE_KEEP_ALIVE"] = "0"
                environment["SURYA_INFERENCE_HOST"] = "127.0.0.1"
                environment["SURYA_INFERENCE_PARALLEL"] = "1"
                with self.lock:
                    if self.stop_event.is_set():
                        raise RuntimeError("interrupted")
                    self.current_job = job_id
                    self.process = subprocess.Popen(
                        [sys.executable, str(ROOT / "scripts/controlled_marker.py"), *argv],
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                        env=environment,
                    )
                started = time.monotonic()
                while self.process.poll() is None:
                    if self.stop_event.wait(0.2) or time.monotonic() - started > self.config.marker_timeout:
                        self.kill(self.process)
                        raise RuntimeError("timeout")
                    if log.tell() > 10_000_000:
                        self.kill(self.process)
                        raise RuntimeError("log_limit")
                if self.process.returncode:
                    raise RuntimeError("process_exit")
            outputs = list((staging / "raw").rglob("*.html"))
            if len(outputs) != 1 or outputs[0].is_symlink():
                raise RuntimeError("invalid_output")
            clean = staging / "clean"
            phase = "sanitizing"
            publish_html(outputs[0], clean, paper_id)
            with self.lock, self.sessions() as session:
                job = session.get(Job, job_id)
                if job.status != "running" or self.stop_event.is_set():
                    raise RuntimeError("interrupted")
                paper = session.get(Paper, paper_id)
                if not paper:
                    raise RuntimeError("deleted")
                job.progress_stage = "publishing"
                relative = f"papers/{paper_id}/derivatives/marker/{job.fingerprint}-{job.id}"
                target = self.config.path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(clean, target)
                paper.html_path = relative + "/article.html"
                job.result_path, job.status, job.progress_stage = paper.html_path, "succeeded", "complete"
                job.finished_at = now()
                session.commit()
        except Exception as exc:
            logging.getLogger("paperflow").error(
                "job=%s phase=%s error=%s frames=%s",
                job_id,
                phase,
                type(exc).__name__,
                [
                    (Path(frame.filename).name, frame.lineno, frame.name)
                    for frame in traceback.extract_tb(exc.__traceback__)
                ],
            )
            with self.sessions() as session:
                job = session.get(Job, job_id)
                if job and job.status == "running":
                    job.status = "failed"
                    job.error_code = "INTERRUPTED" if self.stop_event.is_set() else "CONVERSION_FAILED"
                    job.error_message = "Marker 转换未完成。请检查 CLI、首次模型下载、llama-server 和内存后重试；PDF 可继续阅读。"
                    job.finished_at = now()
                    session.commit()
        finally:
            with self.lock:
                self.process = None
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
