// Apretón de manos del Modo Jean: Sonia y el invitado se giran un poco el uno
// hacia el otro y se dan la mano derecha.
//
// Genies no trae animación de dar la mano, así que cada brazo derecho se lleva
// con IK de dos huesos (hombro, codo, muñeca) a un punto entre los dos, encima
// de lo que suene (el reposo). Las palmas quedan enfrentadas y juntas, con el
// pulgar arriba y los dedos algo cerrados; la mano sube y baja un par de veces.
//
// De cara al público, uno de los dos tiene la mano derecha del lado de fuera:
// ese (el invitado, a la izquierda de Sonia) se gira más hacia el otro, y
// Sonia, que la tiene del lado de dentro, menos. El punto de encuentro sale de
// los hombros derechos de los dos y de lo que mide su brazo, así que vale para
// avatares de cualquier tamaño (los de Genies tienen el brazo corto).
//
// Begin() lanza la secuencia entera: girarse, acercar la mano, estrechar,
// soltar y volver de frente. IsDone dice cuándo ha terminado; Cancel() suelta
// deprisa. Todo con pesos que suben y bajan suave, así que nunca salta.
//
// Corre en LateUpdate después de la animación, de la presencia (10500) y del
// motor de comportamiento de Genies (11000), y antes de la cabeza (12010), los
// ojos y la cara: ellos ven ya el brazo en su sitio.
//
// Las medidas de la mano (hacia dónde van los dedos y de qué lado queda el
// pulgar) se toman de los huesos de cada avatar, no se dan por supuestas: así
// vale igual para Genies que para el doble del editor.

using UnityEngine;

namespace Sonia
{
    /// <summary>Lleva las manos derechas de dos avatares a estrecharse, con IK de dos huesos.</summary>
    [DefaultExecutionOrder(11200)]
    [DisallowMultipleComponent]
    public class HandshakeRig : MonoBehaviour
    {
        [Header("Tiempos (segundos)")]
        [SerializeField]
        [Tooltip("Giro hacia el otro antes de dar la mano.")]
        private float turnSeconds = 0.7f;

        [SerializeField]
        [Tooltip("Del brazo en reposo a la mano en el punto de encuentro.")]
        private float reachSeconds = 0.6f;

        [SerializeField]
        [Tooltip("Con las manos estrechadas, subiendo y bajando.")]
        private float shakeSeconds = 1.5f;

        [SerializeField]
        [Tooltip("De la mano estrechada al brazo en reposo.")]
        private float releaseSeconds = 0.6f;

        [Header("Giro")]
        [SerializeField]
        [Range(0f, 60f)]
        [Tooltip("Grados que gira la raíz de quien tiene la mano derecha del lado del otro (Sonia).")]
        private float nearTurnDegrees = 20f;

        [SerializeField]
        [Range(0f, 80f)]
        [Tooltip("Grados que gira la raíz de quien tiene la mano derecha del lado de fuera (el invitado).")]
        private float farTurnDegrees = 45f;

        [SerializeField]
        [Range(0f, 45f)]
        [Tooltip("Grados que gira además el tronco (repartidos entre las vértebras) hacia el otro.")]
        private float torsoTurnDegrees = 12f;

        [Header("Mano")]
        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Punto de encuentro, desde el medio de los dos hombros derechos: cuánto hacia delante, en largos de brazo.")]
        private float meetForwardOfArm = 0.3f;

        [SerializeField]
        [Range(0f, 1f)]
        [Tooltip("Lo mismo hacia abajo, en largos de brazo (la mano queda algo por encima de la cintura).")]
        private float meetDropOfArm = 0.55f;

        [SerializeField]
        [Range(0f, 0.15f)]
        [Tooltip("De la muñeca al centro de la palma (metros): la muñeca queda así de atrás del punto de encuentro.")]
        private float palmLength = 0.05f;

        [SerializeField]
        [Range(0f, 0.05f)]
        [Tooltip("Grosor de una mano (metros): las palmas quedan juntas, no una dentro de otra.")]
        private float handThickness = 0.025f;

        [SerializeField]
        [Range(0f, 45f)]
        [Tooltip("Grados que se cierra cada falange de los dedos (sin el pulgar) al estrechar.")]
        private float fingerCurlDegrees = 22f;

        [SerializeField]
        [Range(0f, 30f)]
        [Tooltip("Inclinación de los dedos hacia abajo respecto a la horizontal.")]
        private float fingerPitchDegrees = 10f;

        [SerializeField]
        [Tooltip("Hacia dónde apunta el codo, respecto al hombro (en los ejes del avatar: derecha, arriba, delante).")]
        private Vector3 elbowHint = new Vector3(0.15f, -0.45f, -0.1f);

        [Header("Estrechar")]
        [SerializeField]
        [Range(0f, 0.08f)]
        [Tooltip("Cuánto sube y baja la mano (metros).")]
        private float shakeAmplitude = 0.025f;

        [SerializeField]
        [Range(0.5f, 5f)]
        [Tooltip("Veces por segundo.")]
        private float shakeFrequency = 2.2f;

        private readonly Participant _first = new Participant();
        private readonly Participant _second = new Participant();
        private float _time = -1f;
        private bool _cancelled;
        private float _cancelFrom;
        private float _cancelReach;
        private float _cancelTurn;

        /// <summary>Cierto mientras dura la secuencia (desde Begin hasta volver de frente).</summary>
        public bool IsActive
        {
            get { return _time >= 0f; }
        }

        /// <summary>Cierto cuando ya terminó (o nunca empezó).</summary>
        public bool IsDone
        {
            get { return _time < 0f; }
        }

        /// <summary>Cierto mientras las manos están juntas (para mirarse a la cara).</summary>
        public bool HandsJoined
        {
            get { return IsActive && ReachWeight(_time) > 0.5f; }
        }

        /// <summary>Duración de la secuencia completa.</summary>
        public float Duration
        {
            get { return ShakeStart + shakeSeconds + releaseSeconds + (turnSeconds * 0.6f); }
        }

        private float ReachStart
        {
            get { return turnSeconds * 0.5f; }
        }

        private float ShakeStart
        {
            get { return ReachStart + reachSeconds; }
        }

        /// <summary>
        /// Empieza: <paramref name="first"/> (Sonia) y <paramref name="second"/>
        /// (el invitado) se dan la mano derecha. Tienen que estar de pie en su
        /// sitio, mirando al público. Devuelve falso si a alguno le faltan huesos.
        /// </summary>
        public bool Begin(Animator first, Animator second)
        {
            // Uno a medias se termina antes: si no, su giro pasaría por el reposo.
            if (IsActive)
            {
                Finish();
            }

            if (!_first.Bind(first) || !_second.Bind(second))
            {
                Debug.LogWarning("[Sonia] Apretón de manos: a un avatar le faltan huesos del brazo derecho; se salta.", this);
                _time = -1f;
                return false;
            }

            _first.CaptureRest();
            _second.CaptureRest();
            _cancelled = false;
            _time = 0f;
            return true;
        }

        /// <summary>Suelta ya (por ejemplo, si el orquestador termina el Modo Jean a mitad).</summary>
        public void Cancel()
        {
            if (!IsActive || _cancelled)
            {
                return;
            }

            _cancelled = true;
            _cancelFrom = _time;
            _cancelReach = ReachWeight(_time);
            _cancelTurn = TurnWeight(_time);
        }

        private void LateUpdate()
        {
            if (!IsActive)
            {
                return;
            }

            if (!_first.IsValid || !_second.IsValid)
            {
                // Cambió un avatar a mitad: se deja como esté, sin brazo forzado.
                _time = -1f;
                return;
            }

            _time += Time.deltaTime;
            float turn;
            float reach;
            float shake;
            if (_cancelled)
            {
                // Medio segundo para volver del punto en que estuviera.
                float k = Mathf.Clamp01((_time - _cancelFrom) / 0.5f);
                float ease = Smooth(1f - k);
                turn = _cancelTurn * ease;
                reach = _cancelReach * ease;
                shake = 0f;
                if (k >= 1f)
                {
                    Finish();
                    return;
                }
            }
            else
            {
                turn = TurnWeight(_time);
                reach = ReachWeight(_time);
                shake = ShakeOffset(_time);
                if (_time >= Duration)
                {
                    Finish();
                    return;
                }
            }

            Vector3 toSecond = Flat(_second.Root.position - _first.Root.position);
            if (toSecond.sqrMagnitude < 0.0001f)
            {
                return;
            }

            toSecond.Normalize();
            _first.ApplyTurn(toSecond, nearTurnDegrees, farTurnDegrees, torsoTurnDegrees, turn);
            _second.ApplyTurn(-toSecond, nearTurnDegrees, farTurnDegrees, torsoTurnDegrees, turn);
            if (reach <= 0.0001f)
            {
                return;
            }

            // Punto de encuentro: entre los dos hombros derechos, algo delante y
            // abajo, a la medida de sus brazos.
            float arm = (_first.ArmLength + _second.ArmLength) * 0.5f;
            Vector3 forward = Flat(_first.Root.forward + _second.Root.forward);
            forward = forward.sqrMagnitude > 0.0001f ? forward.normalized : Vector3.zero;
            Vector3 meet = ((_first.Shoulder + _second.Shoulder) * 0.5f)
                           + (forward * (arm * meetForwardOfArm))
                           + (Vector3.down * (arm * meetDropOfArm))
                           + (Vector3.up * shake);
            _first.Reach(meet, toSecond, this, reach);
            _second.Reach(meet, -toSecond, this, reach);
        }

        private void Finish()
        {
            _first.RestoreRest();
            _second.RestoreRest();
            _time = -1f;
        }

        // ------------------------------------------------------------------
        // Curvas
        // ------------------------------------------------------------------

        private float TurnWeight(float t)
        {
            float back = ShakeStart + shakeSeconds + (releaseSeconds * 0.4f);
            float inWeight = Smooth(Mathf.Clamp01(t / Mathf.Max(0.01f, turnSeconds)));
            float outWeight = 1f - Smooth(Mathf.Clamp01((t - back) / Mathf.Max(0.01f, turnSeconds * 0.6f)));
            return Mathf.Min(inWeight, outWeight);
        }

        private float ReachWeight(float t)
        {
            float inWeight = Smooth(Mathf.Clamp01((t - ReachStart) / Mathf.Max(0.01f, reachSeconds)));
            float release = ShakeStart + shakeSeconds;
            float outWeight = 1f - Smooth(Mathf.Clamp01((t - release) / Mathf.Max(0.01f, releaseSeconds)));
            return Mathf.Min(inWeight, outWeight);
        }

        private float ShakeOffset(float t)
        {
            float local = t - ShakeStart;
            if (local <= 0f || local >= shakeSeconds)
            {
                return 0f;
            }

            // Arranca y acaba en cero con una envolvente suave.
            float envelope = Mathf.Sin(Mathf.PI * (local / shakeSeconds));
            return Mathf.Sin(2f * Mathf.PI * shakeFrequency * local) * shakeAmplitude * envelope;
        }

        private static float Smooth(float x)
        {
            return x * x * (3f - (2f * x));
        }

        private static Vector3 Flat(Vector3 v)
        {
            v.y = 0f;
            return v;
        }

        // ------------------------------------------------------------------
        // Cada avatar
        // ------------------------------------------------------------------

        private sealed class Participant
        {
            private static readonly HumanBodyBones[] TorsoBones =
            {
                HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.UpperChest
            };

            private static readonly HumanBodyBones[] FingerBones =
            {
                HumanBodyBones.RightIndexProximal, HumanBodyBones.RightIndexIntermediate, HumanBodyBones.RightIndexDistal,
                HumanBodyBones.RightMiddleProximal, HumanBodyBones.RightMiddleIntermediate, HumanBodyBones.RightMiddleDistal,
                HumanBodyBones.RightRingProximal, HumanBodyBones.RightRingIntermediate, HumanBodyBones.RightRingDistal,
                HumanBodyBones.RightLittleProximal, HumanBodyBones.RightLittleIntermediate, HumanBodyBones.RightLittleDistal
            };

            public Transform Root;
            private Animator _animator;
            private Transform _shoulder;
            private Transform _elbow;
            private Transform _wrist;
            private Transform[] _torso = new Transform[0];
            private Transform[] _fingers = new Transform[0];
            private Vector3 _fingerLocal = Vector3.forward;
            private Vector3 _thumbLocal = Vector3.up;
            private Quaternion _restRotation = Quaternion.identity;

            public bool IsValid
            {
                get { return _animator != null && Root != null && _shoulder != null && _elbow != null && _wrist != null; }
            }

            /// <summary>Hombro derecho, ahora.</summary>
            public Vector3 Shoulder
            {
                get { return _shoulder.position; }
            }

            /// <summary>Largo del brazo (hombro a codo más codo a muñeca).</summary>
            public float ArmLength { get; private set; }

            public bool Bind(Animator animator)
            {
                _animator = animator;
                Root = animator != null ? animator.transform : null;
                if (animator == null || !animator.isHuman)
                {
                    return false;
                }

                _shoulder = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
                _elbow = animator.GetBoneTransform(HumanBodyBones.RightLowerArm);
                _wrist = animator.GetBoneTransform(HumanBodyBones.RightHand);
                if (_shoulder == null || _elbow == null || _wrist == null)
                {
                    return false;
                }

                System.Collections.Generic.List<Transform> torso = new System.Collections.Generic.List<Transform>();
                foreach (HumanBodyBones bone in TorsoBones)
                {
                    Transform t = animator.GetBoneTransform(bone);
                    if (t != null)
                    {
                        torso.Add(t);
                    }
                }

                _torso = torso.ToArray();
                System.Collections.Generic.List<Transform> fingers = new System.Collections.Generic.List<Transform>();
                foreach (HumanBodyBones bone in FingerBones)
                {
                    Transform t = animator.GetBoneTransform(bone);
                    if (t != null)
                    {
                        fingers.Add(t);
                    }
                }

                _fingers = fingers.ToArray();
                ArmLength = (_elbow.position - _shoulder.position).magnitude + (_wrist.position - _elbow.position).magnitude;
                MeasureHand(animator);
                return true;
            }

            /// <summary>
            /// Ejes de la mano en el espacio del hueso: hacia los dedos (al nudillo
            /// del corazón) y hacia el lado del pulgar, perpendicular al anterior.
            /// El lado del pulgar sale de la línea de nudillos (del meñique al
            /// índice), que está en el plano de la palma; el hueso del pulgar
            /// queda algo hacia la palma y torcería la mano.
            /// </summary>
            private void MeasureHand(Animator animator)
            {
                Transform middle = animator.GetBoneTransform(HumanBodyBones.RightMiddleProximal);
                Transform index = animator.GetBoneTransform(HumanBodyBones.RightIndexProximal);
                Transform little = animator.GetBoneTransform(HumanBodyBones.RightLittleProximal);
                Transform thumb = animator.GetBoneTransform(HumanBodyBones.RightThumbProximal);
                Vector3 finger = middle != null ? _wrist.InverseTransformPoint(middle.position) : Vector3.zero;
                if (finger.sqrMagnitude < 1e-8f)
                {
                    // Sin dedos: la mano sigue al antebrazo.
                    finger = _wrist.InverseTransformDirection(_wrist.position - _elbow.position);
                }

                finger.Normalize();
                Vector3 side = Vector3.zero;
                if (index != null && little != null)
                {
                    side = _wrist.InverseTransformPoint(index.position) - _wrist.InverseTransformPoint(little.position);
                }
                else if (thumb != null)
                {
                    side = _wrist.InverseTransformPoint(thumb.position);
                }

                side = Vector3.ProjectOnPlane(side, finger);
                if (side.sqrMagnitude < 1e-8f)
                {
                    side = Vector3.ProjectOnPlane(Vector3.up, finger);
                }

                _fingerLocal = finger;
                _thumbLocal = side.normalized;
            }

            public void CaptureRest()
            {
                _restRotation = Root.rotation;
            }

            public void RestoreRest()
            {
                if (Root != null)
                {
                    Root.rotation = _restRotation;
                }
            }

            /// <summary>
            /// Se gira hacia <paramref name="toPartner"/>: la raíz (más si tiene la
            /// mano derecha del lado de fuera) y el tronco otro poco.
            /// </summary>
            public void ApplyTurn(Vector3 toPartner, float nearDegrees, float farDegrees, float torsoDegrees, float weight)
            {
                Vector3 facing = Flat(_restRotation * Vector3.forward);
                if (facing.sqrMagnitude < 0.0001f)
                {
                    return;
                }

                bool partnerOnRight = Vector3.Dot(_restRotation * Vector3.right, toPartner) > 0f;
                float rootDegrees = partnerOnRight ? nearDegrees : farDegrees;
                float full = Vector3.SignedAngle(facing.normalized, toPartner, Vector3.up);
                float sign = Mathf.Sign(full);
                float rootAngle = sign * Mathf.Min(Mathf.Abs(full), rootDegrees) * weight;
                Root.rotation = Quaternion.AngleAxis(rootAngle, Vector3.up) * _restRotation;
                if (_torso.Length == 0 || torsoDegrees <= 0f)
                {
                    return;
                }

                // Se reparte entre las vértebras: cada una suma su parte a la de abajo.
                float each = sign * torsoDegrees * weight / _torso.Length;
                for (int i = 0; i < _torso.Length; i++)
                {
                    _torso[i].rotation = Quaternion.AngleAxis(each, Vector3.up) * _torso[i].rotation;
                }
            }

            /// <summary>Lleva la mano derecha al punto de encuentro, con la palma hacia el otro.</summary>
            public void Reach(Vector3 meet, Vector3 toPartner, HandshakeRig rig, float weight)
            {
                // Dedos hacia el otro y algo hacia abajo; pulgar arriba; la palma
                // mira a su izquierda, así que la mano queda a su derecha del punto.
                Vector3 fingers = Quaternion.AngleAxis(rig.fingerPitchDegrees, Vector3.Cross(Vector3.up, toPartner)) * toPartner;
                Vector3 right = Vector3.Cross(Vector3.up, toPartner).normalized;
                Vector3 wristTarget = meet + (right * (rig.handThickness * 0.5f)) - (fingers * rig.palmLength);
                Vector3 pole = _shoulder.position
                               + (Root.right * rig.elbowHint.x)
                               + (Vector3.up * rig.elbowHint.y)
                               + (Root.forward * rig.elbowHint.z);
                SolveArm(wristTarget, pole, weight);

                // La mano, con su propio marco medido en el hueso.
                Vector3 thumbUp = Vector3.ProjectOnPlane(Vector3.up, fingers);
                if (thumbUp.sqrMagnitude < 1e-6f)
                {
                    return;
                }

                Quaternion localFrame = Quaternion.LookRotation(_fingerLocal, _thumbLocal);
                Quaternion worldFrame = Quaternion.LookRotation(fingers, thumbUp.normalized);
                Quaternion target = worldFrame * Quaternion.Inverse(localFrame);
                _wrist.rotation = Quaternion.Slerp(_wrist.rotation, target, weight);

                // Dedos algo cerrados alrededor de la otra mano (el eje va de un
                // lado a otro de la palma: el del pulgar).
                if (rig.fingerCurlDegrees <= 0f)
                {
                    return;
                }

                Vector3 across = _wrist.rotation * _thumbLocal;
                Quaternion curl = Quaternion.AngleAxis(-rig.fingerCurlDegrees * weight, across);
                for (int i = 0; i < _fingers.Length; i++)
                {
                    _fingers[i].rotation = curl * _fingers[i].rotation;
                }
            }

            /// <summary>
            /// IK de dos huesos: el codo en el plano que marca la pista y la
            /// muñeca en el objetivo. Con peso 0 deja el brazo como está.
            /// </summary>
            private void SolveArm(Vector3 target, Vector3 pole, float weight)
            {
                Vector3 shoulder = _shoulder.position;
                Vector3 elbow = _elbow.position;
                Vector3 wrist = _wrist.position;
                float upper = (elbow - shoulder).magnitude;
                float lower = (wrist - elbow).magnitude;
                if (upper < 1e-4f || lower < 1e-4f)
                {
                    return;
                }

                Vector3 goal = Vector3.Lerp(wrist, target, weight);
                Vector3 toGoal = goal - shoulder;
                if (toGoal.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                Vector3 direction = toGoal.normalized;
                float distance = Mathf.Clamp(toGoal.magnitude, Mathf.Abs(upper - lower) + 0.001f, upper + lower - 0.001f);

                // Plano del codo: del de la animación al de la pista, según el peso.
                Vector3 animatedBend = Vector3.ProjectOnPlane(elbow - shoulder, direction);
                Vector3 hintBend = Vector3.ProjectOnPlane(pole - shoulder, direction);
                Vector3 bend;
                if (animatedBend.sqrMagnitude < 1e-8f)
                {
                    bend = hintBend;
                }
                else if (hintBend.sqrMagnitude < 1e-8f)
                {
                    bend = animatedBend;
                }
                else
                {
                    bend = Vector3.Slerp(animatedBend.normalized, hintBend.normalized, weight);
                }

                if (bend.sqrMagnitude < 1e-8f)
                {
                    return;
                }

                bend.Normalize();
                float along = ((upper * upper) - (lower * lower) + (distance * distance)) / (2f * distance);
                float height = Mathf.Sqrt(Mathf.Max(0f, (upper * upper) - (along * along)));
                Vector3 elbowGoal = shoulder + (direction * along) + (bend * height);
                Vector3 wristGoal = shoulder + (direction * distance);

                _shoulder.rotation = Quaternion.FromToRotation(elbow - shoulder, elbowGoal - shoulder) * _shoulder.rotation;
                Vector3 newElbow = _elbow.position;
                _elbow.rotation = Quaternion.FromToRotation(_wrist.position - newElbow, wristGoal - newElbow) * _elbow.rotation;
            }
        }
    }
}
