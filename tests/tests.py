#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import threading
import signal
import json
import re
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from colorama import init, Fore, Style
    init()
    COLORS_AVAILABLE = True
except ImportError:
    COLORS_AVAILABLE = False

class DelayHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)

        delay = 0
        if 'delay' in params:
            try:
                delay = float(params['delay'][0])
            except (ValueError, IndexError):
                delay = 0

        if delay > 0:
            time.sleep(delay)

        response_data = {
            "url": f"http://localhost:{self.server.server_port}{self.path}",
            "method": "GET",
            "delay": delay,
            "headers": dict(self.headers),
            "timestamp": time.time()
        }

        response_json = json.dumps(response_data, indent=2).encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_json)))
        self.end_headers()
        self.wfile.write(response_json)

    def log_message(self, format, *args):
        pass

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class TestHTTPServer:
    def __init__(self, port=0):
        self.server = ThreadingHTTPServer(('localhost', port), DelayHTTPHandler)
        self.server.server_port = self.server.server_address[1]
        self.port = self.server.server_port
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

class TestRunner:
    def __init__(self):
        self.test_results = []
        self.compilation_failed = False
        self.failure_reason = ""
        self.test_servers = []

    def log(self, message, color=None):
        if COLORS_AVAILABLE and color:
            print(f"{color}{message}{Style.RESET_ALL}")
        else:
            print(message)

    def success(self, message):
        self.log(f"✅ {message}", Fore.GREEN)

    def error(self, message):
        self.log(f"❌ {message}", Fore.RED)

    def info(self, message):
        self.log(f"ℹ️  {message}", Fore.BLUE)

    def warning(self, message):
        self.log(f"⚠️  {message}", Fore.YELLOW)

    def check_scripts_exist(self):
        required_scripts = ['compile.sh', 'execute.sh']
        missing_scripts = []

        for script in required_scripts:
            if not os.path.exists(script):
                missing_scripts.append(script)

        if missing_scripts:
            self.failure_reason = f"Отсутствуют скрипты: {', '.join(missing_scripts)}"
            self.error(self.failure_reason)
            return False

        return True

    def check_hedgedcurl_exists(self):
        possible_files = [
            'hedgedcurl.py', 'hedgedcurl.go',
            'hedgedcurl.cpp', 'hedgedcurl.java'
        ]

        for filename in possible_files:
            if os.path.exists(filename):
                self.info(f"Найден файл: {filename}")
                return True

        self.failure_reason = "Не найден файл hedgedcurl с поддерживаемым расширением"
        self.error(self.failure_reason)
        self.error(f"Поддерживаемые файлы: {', '.join(possible_files)}")
        return False

    def compile_code(self):
        self.info("Запуск компиляции...")
        result = subprocess.run(['./compile.sh'], capture_output=True, text=True)
        if result.returncode != 0:
            self.compilation_failed = True
            self.failure_reason = f"Ошибка компиляции: {result.stderr.strip() or result.stdout.strip() or 'Неизвестная ошибка'}"
            self.error(self.failure_reason)
            return False

        self.success("Компиляция завершена успешно")
        return True

    def start_test_servers(self):
        try:
            for _ in range(3):
                server = TestHTTPServer()
                server.start()
                self.test_servers.append(server)
                self.info(f"Запущен тестовый сервер на порту {server.port}")

            time.sleep(0.5)
            return True

        except Exception as e:
            self.error(f"Ошибка запуска тестовых серверов: {e}")
            return False

    def stop_test_servers(self):
        for server in self.test_servers:
            try:
                server.stop()
            except Exception as e:
                self.warning(f"Ошибка остановки сервера: {e}")
        self.test_servers.clear()

    def run_hedgedcurl(self, urls, timeout=30):
        try:
            cmd = ['./execute.sh'] + urls
            start_time = time.time()

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            end_time = time.time()
            execution_time = end_time - start_time

            return {
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'execution_time': execution_time
            }

        except subprocess.TimeoutExpired:
            self.error(f"Таймаут выполнения hedgedcurl ({timeout}s) - слишком долгое исполнение команды")
            return None
        except FileNotFoundError:
            self.error("Не удалось запустить execute.sh")
            return None
        except Exception as e:
            self.error(f"Ошибка при запуске hedgedcurl: {e}")
            return None

    def test_single_url(self):
        if not self.test_servers:
            return False

        server = self.test_servers[0]
        url = f"http://localhost:{server.port}/test"

        self.info("Тестирование с одним URL...")
        result = self.run_hedgedcurl([url])

        if not result:
            return False

        if result['returncode'] != 0:
            self.error(f"hedgedcurl завершился с ошибкой: {result['stderr']}")
            return False

        if not result['stdout'].strip():
            self.error("hedgedcurl не вернул никакого вывода")
            return False

        self.success("Тест с одним URL прошел успешно")
        return True

    def test_hedging_with_delays(self):
        if len(self.test_servers) < 3:
            return False

        urls = [
            f"http://localhost:{self.test_servers[0].port}/test?delay=10",
            f"http://localhost:{self.test_servers[1].port}/test?delay=10",
            f"http://localhost:{self.test_servers[2].port}/test?delay=0"
        ]

        result = self.run_hedgedcurl(urls, timeout=25)

        if not result:
            return False

        if result['returncode'] != 0:
            self.error(f"hedgedcurl завершился с ошибкой: {result['stderr']}")
            return False

        execution_time = result['execution_time']

        MAX_ALLOWED_TIME = 3.0
        if execution_time > MAX_ALLOWED_TIME:
            self.error(f"ПРОВАЛ: hedgedcurl выполнялся {execution_time:.2f}s")
            self.error(f"Превышен лимит {MAX_ALLOWED_TIME}s для многопоточной реализации")
            self.error("Ваша реализация НЕ МНОГОПОТОЧНАЯ (запросы выполняются последовательно)")
            self.error("💡 Используйте параллельное выполнение: asyncio, threading, горутины и т.д.")
            return False
        else:
            self.success(f"OK: hedgedcurl выполнился за {execution_time:.2f}s")

        if 'localhost' in result['stdout'] and '"delay": 0' in result['stdout']:
            self.success("Получен ответ от быстрого сервера (delay=0)")
            return True
        else:
            self.error("Не получен ожидаемый ответ от быстрого сервера")
            return False

    def test_error_handling(self):
        invalid_urls = [
            "http://localhost:99999/nonexistent",
            "invalid-url",
            "http://nonexistent-domain-12345.com/"
        ]

        self.info("Тестирование обработки ошибок...")
        result = self.run_hedgedcurl(invalid_urls, timeout=20)

        if not result:
            return False

        if result['returncode'] == 0:
            self.warning("hedgedcurl завершился успешно при неверных URL")
            self.warning("Ожидалось завершение с ошибкой")
        else:
            self.success("hedgedcurl корректно обработал ошибки")

        return True

    def test_mixed_valid_invalid(self):
        if not self.test_servers:
            return False

        mixed_urls = [
            "http://localhost:99999/nonexistent",
            f"http://localhost:{self.test_servers[0].port}/test?delay=0.5",
            "http://nonexistent-domain-12345.com/"
        ]

        self.info("Тестирование со смешанными валидными/невалидными URL...")
        result = self.run_hedgedcurl(mixed_urls)

        if not result:
            return False

        if result['returncode'] != 0:
            self.warning("hedgedcurl завершился с ошибкой при наличии валидного URL")
        else:
            self.success("hedgedcurl корректно обработал смешанные URL")

        if 'localhost' in result['stdout']:
            self.success("hedgedcurl вернул ответ от валидного сервера")
            return True
        else:
            self.warning("hedgedcurl не вернул ответ от валидного сервера")
            return False

    def test_output_format(self):
        if not self.test_servers:
            return False

        server = self.test_servers[0]
        url = f"http://localhost:{server.port}/test"

        self.info("Тестирование формата вывода...")
        result = self.run_hedgedcurl([url])

        if not result:
            return False

        if result['returncode'] != 0:
            self.error(f"hedgedcurl завершился с ошибкой: {result['stderr']}")
            return False

        output = result['stdout']

        if not ('HTTP/' in output and ('200' in output or '201' in output or '202' in output)):
            self.error("В выводе отсутствует HTTP статус-код (например: HTTP/1.1 200 OK)")
            return False
        else:
            self.success("HTTP статус-код найден в выводе")

        headers_found = False
        for header in ['Content-Type:', 'Content-Length:', 'Date:', 'Server:']:
            if header in output:
                headers_found = True
                break

        if not headers_found:
            self.error("В выводе отсутствуют HTTP заголовки (Content-Type, Content-Length и т.д.)")
            return False
        else:
            self.success("HTTP заголовки найдены в выводе")

        if not ('{' in output and '}' in output and 'localhost' in output):
            self.error("В выводе отсутствует тело ответа")
            return False
        else:
            self.success("Тело ответа найдено в выводе")

        lines = output.split('\n')

        self.success("Тест формата вывода прошел успешно")
        return True

    def test_help_flag(self):
        self.info("Проверка работы флажков -h и --help...")

        result_h = self.run_hedgedcurl(["-h"], timeout=5)
        if not result_h:
            self.error("Не удалось запустить hedgedcurl с флажком -h")
            return False

        if result_h['returncode'] != 0:
            self.error("hedgedcurl -h завершился с ошибкой")
            return False

        if not result_h['stdout'].strip():
            self.error("Флажок -h не вывел справку")
            return False

        self.success("Флажок -h работает корректно")

        result_help = self.run_hedgedcurl(["--help"], timeout=5)
        if not result_help:
            self.error("Не удалось запустить hedgedcurl с флажком --help")
            return False

        if result_help['returncode'] != 0:
            self.error("hedgedcurl --help завершился с ошибкой")
            return False

        if not result_help['stdout'].strip():
            self.error("Флажок --help не вывел справку")
            return False

        self.success("Флажок --help работает корректно")
        self.success("Проверка флажков -h и --help прошла успешно")
        return True

    def test_timeout_flag(self):
        if not self.test_servers:
            return False

        server = self.test_servers[0]
        url = f"http://localhost:{server.port}/test?delay=10"

        self.info("Тестирование флажка --timeout...")

        result = self.run_hedgedcurl(["-t", "1", url], timeout=5)
        if not result:
            return False

        if result['returncode'] != 228:
            self.error(f"Ожидалась ошибка таймаута с кодом возврата 228, но запрос завершился с кодом {result['returncode']}")
            return False

        self.success("Тест таймаута прошел успешно")
        return True

    def run_tests(self):
        self.log("🧪 Начало тестирования домашнего задания №1 - hedgedcurl", Fore.CYAN)

        if not self.check_scripts_exist():
            return False

        if not self.check_hedgedcurl_exists():
            return False

        if not self.compile_code():
            return False

        if not self.start_test_servers():
            return False

        try:
            tests = [
                ("Тест с одним URL", self.test_single_url),
                ("Тест формата вывода", self.test_output_format),
                ("Тест флажка --help", self.test_help_flag),
                ("Тест флажка --timeout", self.test_timeout_flag),
                ("Тест хеджирования с задержками", self.test_hedging_with_delays),
                ("Тест обработки ошибок", self.test_error_handling),
                ("Тест смешанных URL", self.test_mixed_valid_invalid)
            ]

            all_passed = True
            for test_name, test_func in tests:
                self.info(f"Выполнение: {test_name}")
                if test_func():
                    self.test_results.append((test_name, True))
                else:
                    self.test_results.append((test_name, False))
                    all_passed = False
                print()

            return all_passed

        finally:
            self.stop_test_servers()

    def print_summary(self):
        print("=" * 60)
        self.log("📊 ИТОГОВЫЙ ОТЧЁТ", Fore.CYAN)
        print("=" * 60)

        if self.compilation_failed or self.failure_reason:
            if self.failure_reason:
                self.error(f"ПРОВАЛ: {self.failure_reason}")
            else:
                self.error("ПРОВАЛ: Критическая ошибка")
            print("-" * 60)
            self.log("❌ Домашнее задание НЕ выполнено корректно", Fore.RED)
            return

        passed = sum(1 for _, result in self.test_results if result)
        total = len(self.test_results)

        if total == 0:
            self.error("ПРОВАЛ: Тесты не были запущены")
            print("-" * 60)
            self.log("❌ Домашнее задание НЕ выполнено корректно", Fore.RED)
            return

        for test_name, result in self.test_results:
            if result:
                self.success(f"{test_name}")
            else:
                self.error(f"{test_name}")

        print("-" * 60)
        if passed == total:
            self.success(f"Все тесты пройдены: {passed}/{total}")
            self.log("🎉 Поздравляем! hedgedcurl работает корректно!", Fore.GREEN)
        else:
            self.error(f"Тесты пройдены: {passed}/{total}")
            self.log("❌ Есть ошибки, которые нужно исправить", Fore.RED)

def main():
    os.chdir(Path(__file__).parent.parent)

    runner = TestRunner()

    try:
        success = runner.run_tests()
        runner.print_summary()
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        runner.log("\n⏹️  Тестирование прервано пользователем", Fore.YELLOW)
        runner.stop_test_servers()
        sys.exit(1)
    except Exception as e:
        runner.error(f"Критическая ошибка: {e}")
        runner.stop_test_servers()
        sys.exit(1)

if __name__ == "__main__":
    main()