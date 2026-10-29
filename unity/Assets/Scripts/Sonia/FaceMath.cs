// Motion helpers for the face: critically damped springs.
//
// Exponential smoothing (Lerp toward the target) starts at full speed and then
// brakes: on the mouth and brows it reads as a mechanical tic. A critically
// damped spring accelerates and brakes along a curve without overshooting the
// target, which is how a muscle moves. It is the closed-form solution (stable
// with any dt), so 30 or 144 fps makes no difference.

using UnityEngine;

namespace Sonia
{
    /// <summary>Critically damped spring for a scalar value.</summary>
    public struct Spring
    {
        /// <summary>Current value.</summary>
        public float Value;

        /// <summary>Current velocity (units per second).</summary>
        public float Velocity;

        /// <summary>
        /// Advances the spring toward <paramref name="target"/>. <paramref name="frequency"/>
        /// in Hz: at 8 Hz it reaches 90 % in about 70 ms.
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

        /// <summary>Like <see cref="Step"/>, with one frequency for rising and another for falling.</summary>
        public float Step(float target, float riseFrequency, float fallFrequency, float dt)
        {
            return Step(target, target > Value ? riseFrequency : fallFrequency, dt);
        }

        /// <summary>Puts the spring at rest at a value.</summary>
        public void Reset(float value = 0f)
        {
            Value = value;
            Velocity = 0f;
        }

        /// <summary>Kick: adds velocity without moving the value (nods, raising brows).</summary>
        public void Kick(float velocity)
        {
            Velocity += velocity;
        }
    }

    /// <summary>Shape functions for gesture envelopes.</summary>
    public static class FaceCurves
    {
        /// <summary>Smooth rise and fall in [0, 1]: 0 at the ends, 1 at <paramref name="peak"/>.</summary>
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

        /// <summary>Smooth noise in [-1, 1] (centered Perlin).</summary>
        public static float Noise(float seed, float time)
        {
            return (Mathf.PerlinNoise(seed, time) - 0.5f) * 2f;
        }
    }
}
