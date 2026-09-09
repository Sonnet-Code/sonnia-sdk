// Assets de marca de Sonnet Code y sus ajustes de importación.
//
// Los PNG llegan al proyecto con los ajustes por defecto de Unity, que para un
// logo con alfa sobre fondo oscuro no valen: comprime con pérdida y genera
// mipmaps que emborronan el trazo. Aquí se fuerzan los ajustes buenos y se
// resuelven las rutas en un solo sitio, porque los usan tanto el HUD como el
// telón de fondo.

#if UNITY_EDITOR

using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Rutas y ajustes de importación de los assets de marca.</summary>
    public static class SoniaBrandAssets
    {
        private const string UiFolder = "Assets/UI";

        /// <summary>Logo con texto blanco, para fondo oscuro. Es el que va en el HUD.</summary>
        public const string LogoPath = UiFolder + "/logo-sonnet.png";

        /// <summary>Versión con texto navy, por si algún día el fondo es claro.</summary>
        public const string LogoColorPath = UiFolder + "/logo-sonnet-color.png";

        /// <summary>Fondo corporativo 16:9 con degradado, la S de marca de agua y el logo.</summary>
        public const string BackgroundPath = UiFolder + "/sonnet-bg-navy-4k.png";

        /// <summary>Carga el sprite del logo, dejando antes sus ajustes de importación.</summary>
        public static Sprite LoadLogoSprite()
        {
            ApplySpriteImport(LogoPath);
            ApplySpriteImport(LogoColorPath);

            Sprite sprite = AssetDatabase.LoadAssetAtPath<Sprite>(LogoPath);
            if (sprite == null)
            {
                Debug.LogWarning(
                    "[Sonia] No se encontró el sprite " + LogoPath + "; el HUD irá sin logo.");
            }

            return sprite;
        }

        /// <summary>Carga la textura del fondo corporativo.</summary>
        public static Texture2D LoadBackgroundTexture()
        {
            ApplyTextureImport(BackgroundPath);

            Texture2D texture = AssetDatabase.LoadAssetAtPath<Texture2D>(BackgroundPath);
            if (texture == null)
            {
                Debug.LogWarning(
                    "[Sonia] No se encontró la textura " + BackgroundPath
                    + "; el telón se queda con el degradado generado por código.");
            }

            return texture;
        }

        /// <summary>Deja un PNG como sprite de interfaz: sin mipmaps y sin compresión con pérdida.</summary>
        public static void ApplySpriteImport(string path)
        {
            TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null)
            {
                return;
            }

            bool changed = false;

            if (importer.textureType != TextureImporterType.Sprite)
            {
                importer.textureType = TextureImporterType.Sprite;
                changed = true;
            }

            if (importer.spriteImportMode != SpriteImportMode.Single)
            {
                importer.spriteImportMode = SpriteImportMode.Single;
                changed = true;
            }

            if (importer.mipmapEnabled)
            {
                importer.mipmapEnabled = false;
                changed = true;
            }

            if (!importer.alphaIsTransparency)
            {
                importer.alphaIsTransparency = true;
                changed = true;
            }

            if (importer.textureCompression != TextureImporterCompression.CompressedHQ)
            {
                importer.textureCompression = TextureImporterCompression.CompressedHQ;
                changed = true;
            }

            if (importer.wrapMode != TextureWrapMode.Clamp)
            {
                importer.wrapMode = TextureWrapMode.Clamp;
                changed = true;
            }

            if (changed)
            {
                importer.SaveAndReimport();
            }
        }

        /// <summary>Deja un PNG como textura normal para un material del mundo.</summary>
        public static void ApplyTextureImport(string path)
        {
            TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null)
            {
                return;
            }

            bool changed = false;

            if (importer.textureType != TextureImporterType.Default)
            {
                importer.textureType = TextureImporterType.Default;
                changed = true;
            }

            if (!importer.mipmapEnabled)
            {
                importer.mipmapEnabled = true;
                changed = true;
            }

            if (importer.textureCompression != TextureImporterCompression.CompressedHQ)
            {
                importer.textureCompression = TextureImporterCompression.CompressedHQ;
                changed = true;
            }

            // Clamp: el telón muestra un recorte de la textura y con Repeat se
            // vería el borde opuesto pegado al lado.
            if (importer.wrapMode != TextureWrapMode.Clamp)
            {
                importer.wrapMode = TextureWrapMode.Clamp;
                changed = true;
            }

            if (changed)
            {
                importer.SaveAndReimport();
            }
        }
    }
}

#endif
