// Fingerprint of a Genies avatar definition (the SDK's JSON).
//
// It tells whether two definitions are the same character without depending on
// formatting: they may arrive indented from a file, compact from the
// orchestrator, and with Windows or Mac line endings.


namespace Sonia
{
    /// <summary>Compares Genies avatar definitions by content.</summary>
    public static class GeniesDefinition
    {
        /// <summary>
        /// Fingerprint of a JSON definition. It ignores spaces, tabs and line
        /// breaks outside strings (and the BOM). It is 64-bit FNV-1a: it only tells
        /// whether the definition changed and is not cryptographic. Empty if there
        /// is no definition.
        /// </summary>
        public static string Hash(string json)
        {
            if (string.IsNullOrEmpty(json))
            {
                return string.Empty;
            }

            const ulong Prime = 1099511628211UL;
            ulong hash = 14695981039346656037UL;
            bool inString = false;
            bool escaped = false;
            bool any = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (inString)
                {
                    if (escaped)
                    {
                        escaped = false;
                    }
                    else if (c == '\\')
                    {
                        escaped = true;
                    }
                    else if (c == '"')
                    {
                        inString = false;
                    }
                }
                else if (c == '"')
                {
                    inString = true;
                }
                else if (char.IsWhiteSpace(c) || c == '﻿')
                {
                    continue;
                }

                hash ^= (byte)(c & 0xFF);
                hash *= Prime;
                hash ^= (byte)(c >> 8);
                hash *= Prime;
                any = true;
            }

            return any ? hash.ToString("x16") : string.Empty;
        }

        /// <summary>True if both are the same definition (two empty ones do not count as equal).</summary>
        public static bool Same(string a, string b)
        {
            string hash = Hash(a);
            return hash.Length > 0 && hash == Hash(b);
        }
    }
}
