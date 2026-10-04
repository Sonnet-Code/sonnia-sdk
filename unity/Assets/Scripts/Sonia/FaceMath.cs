// Utilidades de movimiento para la cara: muelles críticamente amortiguados.
//
// Un suavizado exponencial (Lerp hacia el objetivo) arranca a toda velocidad y
// frena: en la boca y en las cejas se lee como un tic mecánico. Un muelle
// críticamente amortiguado acelera y frena con curva, sin pasarse del objetivo,
// que es como se mueve un músculo. Es la solución cerrada (estable con
// cualquier dt), así que da lo mismo 30 que 144 fps.

using UnityEngine;

namespace Sonia
{
    /// <summary>Muelle críticamente amortiguado de un valor escalar.</summary>
    public struct Spring
    {
        /// <summary>Valor actual.</summary>
        public float Value;

        /// <summary>Velocidad actual (unidades por segundo).</summary>
        public float Velocity;

        /// <summary>
        /// Avanza el muelle hacia <paramref name="target"/>. <paramref name="frequency"/>
        /// en Hz: con 8 Hz llega al 90 % en unos 70 ms.
        /// </summary>
        public float Step(float target, float frequency, float dt)
        {
            float omega = 2f * Mathf.PI * Mathf.Max(0.01f, frequency);
            float x = Value - target;
            float exp = Mathf.Exp(-omega * dt);
            float temp = (Velocity + omega * x) * dt;
            Velocity = (Velocity - omega * temp) * exp;
            Value = target + (x + temp) * exp;
            return Value;
        }

        /// <summary>Como <see cref="Step"/>, con una frecuencia para subir y otra para bajar.</summary>
        public float Step(float target, float riseFrequency, float fallFrequency, float dt)
        {
            return Step(target, target > Value ? riseFrequency : fallFrequency, dt);
        }

        /// <summary>Lleva el muelle a un valor en reposo.</summary>
        public void Reset(float value = 0f)
        {
            Value = value;
            Velocity = 0f;
        }

        /// <summary>Empujón: suma velocidad sin mover el valor (asentimientos, levantar cejas).</summary>
        public void Kick(float velocity)
        {
            Velocity += velocity;
        }
    }

    /// <summary>Funciones de forma para envolventes de gestos.</summary>
    public static class FaceCurves
    {
        /// <summary>Subida y bajada suave en [0, 1]: 0 en los extremos, 1 en <paramref name="peak"/>.</summary>
        public static float Bump(float t, float peak = 0.3f)
        {
            if (t <= 0f || t >= 1f)
            {
                return 0f;
            }

            if (t < peak)
            {
                float a = t / peak;
                return a * a * (3f - 2f * a);
            }

            float b = 1f - ((t - peak) / (1f - peak));
            return b * b * (3f - 2f * b);
        }

        /// <summary>Ruido suave en [-1, 1] (Perlin centrado).</summary>
        public static float Noise(float seed, float time)
        {
            return (Mathf.PerlinNoise(seed, time) - 0.5f) * 2f;
        }
    }
}
