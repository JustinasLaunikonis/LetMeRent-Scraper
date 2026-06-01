import logging
import subprocess
import sys
import threading
import uuid

from api.config import SCRAPY_PROJECT_DIR
from api.logging_utils import docker_log, utc_now


class SpiderJobRunner:
    def __init__(self):
        self._job_lock = threading.Lock()
        self._current_job = None
        self._jobs = {}

    def start(self, spiders, city=None, extra_args=None):
        extra_args = list(extra_args or [])

        if city:
            extra_args.extend(["-a", f"city={city}"])

        job_id = str(uuid.uuid4())
        docker_log("INFO", f"spider_job_request spiders={spiders} city={city} extra_args={extra_args}")

        with self._job_lock:
            job = {
                "id": job_id,
                "status": "running",
                "spiders": spiders,
                "city": city,
                "args": extra_args,
                "started_at": utc_now(),
            }
            self._jobs[job_id] = job
            self._current_job = job

        thread = threading.Thread(target=self._run, args=(job_id, spiders, extra_args), daemon=True)
        thread.start()
        return job, None

    def _run(self, job_id, spiders, extra_args):
        results = []
        docker_log("INFO", f"spider_job_started job_id={job_id} spiders={','.join(spiders)} args={extra_args}")

        for spider in spiders:
            result = self._run_spider(job_id, spider, extra_args)
            results.append(result)

            if result["returncode"] != 0:
                break

        status = "completed" if all(result["returncode"] == 0 for result in results) else "failed"
        docker_log("INFO", f"spider_job_finished job_id={job_id} status={status}")

        with self._job_lock:
            job = self._jobs.get(job_id, {"id": job_id})
            job.update({
                "id": job_id,
                "status": status,
                "spiders": spiders,
                "results": results,
                "finished_at": utc_now(),
            })
            self._jobs[job_id] = job
            self._current_job = job

    def _run_spider(self, job_id, spider, extra_args):
        docker_log("INFO", f"spider_job_spider_started job_id={job_id} spider={spider}")
        started_at = utc_now()
        command = [sys.executable, "-m", "scrapy", "crawl", spider, *extra_args]
        docker_log("INFO", f"spider_job_command job_id={job_id} spider={spider} command={command}")

        process = subprocess.Popen(
            command,
            cwd=SCRAPY_PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout_thread = self._log_stream(process.stdout, logging.INFO, job_id, spider, "stdout")
        stderr_thread = self._log_stream(process.stderr, logging.ERROR, job_id, spider, "stderr")
        returncode = process.wait()
        stdout_thread.join()
        stderr_thread.join()

        if returncode == 0:
            docker_log("INFO", f"spider_job_spider_completed job_id={job_id} spider={spider}")
        else:
            docker_log("ERROR", f"spider_job_spider_failed job_id={job_id} spider={spider} returncode={returncode}")

        return {
            "spider": spider,
            "status": "completed" if returncode == 0 else "failed",
            "returncode": returncode,
            "started_at": started_at,
            "finished_at": utc_now(),
        }

    def _log_stream(self, stream, level, job_id, spider, stream_name):
        thread = threading.Thread(
            target=self._drain_stream,
            args=(stream, level, job_id, spider, stream_name),
        )
        thread.start()
        return thread

    @staticmethod
    def _drain_stream(stream, level, job_id, spider, stream_name):
        for line in iter(stream.readline, ""):
            line = line.rstrip()
            if line:
                level_name = logging.getLevelName(level)
                docker_log(level_name, f"spider_output job_id={job_id} spider={spider} stream={stream_name} {line}")
        stream.close()
