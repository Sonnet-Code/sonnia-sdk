// Arranca el orquestador que va empaquetado dentro de la app (builds de macOS y Windows).
//
// La build lleva el orquestador congelado (scripts/build_orquestador.sh) con el
// .env del repo al lado del ejecutable (lo copia SoniaPlayerBuildFixes):
//   macOS    Sonia.app/Contents/Resources/orquestador/sonia-orquestador/sonia-orquestador
//   Windows  Sonia_Data/orquestador/sonia-orquestador/sonia-orquestador.exe
//
// Al abrir la app se lanza si nadie escucha ya en el puerto del orquestador (así
// manda uno que ya esté corriendo, como el de desarrollo), se relanza si se cae
// (igual que scripts/kiosk.sh) y se cierra al salir. En el editor no se lanza
// nunca; en la app, -sin-orquestador lo desactiva.
//
// Lo de cada equipo (cache/, overrides.env del backoffice y los registros) va en
// SONIA_HOME, fuera de la app: ~/Library/Application Support/Sonia en macOS y
// %APPDATA%\Sonia en Windows (la misma carpeta que sonia/paths.py).
//
// El orquestador recibe el PID de la app (SONIA_PARENT_PID) y se cierra solo si
// la app muere de golpe (sonia/parent.py): si no, se quedaba huérfano con el
// micrófono abierto y la sesión de GPT-Live gastando.

using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace Sonia
{
    /// <summary>Lanza, vigila y cierra el orquestador empaquetado en la app.</summary>
    public class OrchestratorProcess : MonoBehaviour
    {
        /// <summary>Argumento de la app que desactiva el orquestador empaquetado.</summary>
        public const string DisableArgument = "-sin-orquestador";

        private const int Port = 8765;
        private const float PortCheckSeconds = 5f;
        private const float MaxRestartDelaySeconds = 30f;
        private const float HealthySeconds = 60f;
        private const int KeptLogs = 10;

        private string _executable;
        private string _home;
        private Process _process;
        private StreamWriter _log;
        private readonly object _logLock = new object();
        private float _nextAttempt;
        private float _startedAt;
        private int _failures;
        private bool _quitting;

        /// <summary>Ruta del ejecutable empaquetado en esta plataforma (exista o no).</summary>
        public static string PackagedExecutable()
        {
#if UNITY_STANDALONE_OSX
            return Path.Combine(Application.dataPath, "Resources", "orquestador", "sonia-orquestador", "sonia-orquestador");
#elif UNITY_STANDALONE_WIN
            return Path.Combine(Application.dataPath, "orquestador", "sonia-orquestador", "sonia-orquestador.exe");
#else
            return null;
#endif
        }

        /// <summary>Carpeta de datos de este equipo (SONIA_HOME), la misma que usa el orquestador.</summary>
        public static string HomeDirectory()
        {
#if UNITY_STANDALONE_WIN
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Sonia");
#else
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Personal), "Library", "Application Support", "Sonia");
#endif
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void CreateOnStart()
        {
            if (Application.isEditor || Array.IndexOf(Environment.GetCommandLineArgs(), DisableArgument) >= 0)
            {
                return;
            }

            string executable = PackagedExecutable();
            if (string.IsNullOrEmpty(executable) || !File.Exists(executable))
            {
                Debug.Log("[Sonia] Esta app no lleva orquestador empaquetado: se espera uno externo en el puerto " + Port + ".");
                return;
            }

            GameObject go = new GameObject("SoniaOrquestador");
            DontDestroyOnLoad(go);
            OrchestratorProcess process = go.AddComponent<OrchestratorProcess>();
            process._executable = executable;
            process._home = HomeDirectory();
        }

        private void Update()
        {
            if (_quitting || Time.realtimeSinceStartup < _nextAttempt)
            {
                return;
            }

            if (_process != null)
            {
                if (!HasExited(_process))
                {
                    return;
                }

                int code = SafeExitCode(_process);
                _process.Dispose();
                _process = null;
                bool healthy = Time.realtimeSinceStartup - _startedAt >= HealthySeconds;
                _failures = healthy ? 1 : _failures + 1;
                float delay = Mathf.Min(MaxRestartDelaySeconds, Mathf.Pow(2f, _failures));
                WriteLog("[unity] el orquestador salió (código " + code + "); se relanza en " + delay.ToString("F0") + " s");
                Debug.LogWarning("[Sonia] El orquestador se cerró (código " + code + "); se relanza en " + delay.ToString("F0") + " s.");
                _nextAttempt = Time.realtimeSinceStartup + delay;
                return;
            }

            _nextAttempt = Time.realtimeSinceStartup + PortCheckSeconds;
            if (PortInUse())
            {
                // Ya hay un orquestador (de desarrollo o de una ejecución anterior): manda ese.
                return;
            }

            Launch();
        }

        private void Launch()
        {
            try
            {
                Directory.CreateDirectory(_home);
                OpenLog();
                ProcessStartInfo info = new ProcessStartInfo(_executable, "run")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    // Sin esto los acentos del registro salían como «??».
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                    WorkingDirectory = Path.GetDirectoryName(_executable)
                };
                info.EnvironmentVariables["SONIA_HOME"] = _home;
                info.EnvironmentVariables["SONIA_PARENT_PID"] = Process.GetCurrentProcess().Id.ToString();
                info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
                info.EnvironmentVariables["PYTHONUTF8"] = "1";
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                _process = new Process { StartInfo = info, EnableRaisingEvents = false };
                _process.OutputDataReceived += (_, e) => WriteLog(e.Data);
                _process.ErrorDataReceived += (_, e) => WriteLog(e.Data);
                _process.Start();
                _process.BeginOutputReadLine();
                _process.BeginErrorReadLine();
                _startedAt = Time.realtimeSinceStartup;
                Debug.Log("[Sonia] Orquestador empaquetado en marcha (pid " + _process.Id + "); registro en " + Path.Combine(_home, "logs") + ".");
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] No se pudo lanzar el orquestador empaquetado: " + exception.Message);
                _process = null;
                _failures++;
                _nextAttempt = Time.realtimeSinceStartup + Mathf.Min(MaxRestartDelaySeconds, Mathf.Pow(2f, _failures));
            }
        }

        private void OnApplicationQuit()
        {
            _quitting = true;
            Stop();
        }

        private void OnDestroy()
        {
            if (!_quitting)
            {
                _quitting = true;
                Stop();
            }
        }

        /// <summary>Cierra el orquestador con calma (cierra la sesión de GPT-Live) y, si no, a la fuerza.</summary>
        private void Stop()
        {
            Process process = _process;
            _process = null;
            if (process == null)
            {
                CloseLog();
                return;
            }

            try
            {
                if (!process.HasExited)
                {
#if !UNITY_STANDALONE_WIN
                    // SIGINT: el orquestador sale como con Ctrl+C.
                    kill(process.Id, 2);
                    if (!process.WaitForExit(5000))
                    {
                        process.Kill();
                    }
#else
                    process.Kill();
#endif
                }
            }
            catch (Exception exception)
            {
                Debug.LogWarning("[Sonia] Al cerrar el orquestador: " + exception.Message);
            }
            finally
            {
                process.Dispose();
                CloseLog();
            }
        }

#if !UNITY_STANDALONE_WIN
        [DllImport("libc")]
        private static extern int kill(int pid, int sig);
#endif

        private static bool PortInUse()
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    IAsyncResult attempt = client.BeginConnect("127.0.0.1", Port, null, null);
                    bool connected = attempt.AsyncWaitHandle.WaitOne(TimeSpan.FromMilliseconds(250)) && client.Connected;
                    if (connected)
                    {
                        client.EndConnect(attempt);
                    }

                    return connected;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static bool HasExited(Process process)
        {
            try
            {
                return process.HasExited;
            }
            catch (Exception)
            {
                return true;
            }
        }

        private static int SafeExitCode(Process process)
        {
            try
            {
                return process.ExitCode;
            }
            catch (Exception)
            {
                return -1;
            }
        }

        // ------------------------------------------------------------------
        // Registro: un archivo por arranque en SONIA_HOME/logs, se guardan los últimos.
        // ------------------------------------------------------------------

        private void OpenLog()
        {
            lock (_logLock)
            {
                if (_log != null)
                {
                    return;
                }

                string folder = Path.Combine(_home, "logs");
                Directory.CreateDirectory(folder);
                string[] old = Directory.GetFiles(folder, "orquestador-*.log");
                Array.Sort(old);
                for (int i = 0; i < old.Length - (KeptLogs - 1); i++)
                {
                    File.Delete(old[i]);
                }

                string path = Path.Combine(folder, "orquestador-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".log");
                _log = new StreamWriter(path, true) { AutoFlush = true };
            }
        }

        private void WriteLog(string line)
        {
            if (line == null)
            {
                return;
            }

            lock (_logLock)
            {
                _log?.WriteLine(line);
            }
        }

        private void CloseLog()
        {
            lock (_logLock)
            {
                _log?.Dispose();
                _log = null;
            }
        }
    }
}
