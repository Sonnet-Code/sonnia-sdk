// Ajustes de importación de los recursos de la pantalla del stand
// (Resources/Stage, los genera scripts/stage_assets.py): sprites sin mipmaps ni
// compresión para que los bordes y el degradado del fondo salgan limpios, y con su
// corte en 9 las formas redondeadas y la sombra. El QR sí lleva mipmaps: se pinta a
// 4x y sin ellos sus curvas salían dentadas al reducirlo a los 176 px de pantalla.

using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Deja los PNG de Resources/Stage como los espera StageScreen.</summary>
    public class SoniaStageAssets : AssetPostprocessor
    {
        private const string Folder = "Assets/Resources/Stage/";

        private void OnPreprocessTexture()
        {
            if (!assetPath.StartsWith(Folder))
            {
                return;
            }

            TextureImporter importer = (TextureImporter)assetImporter;
            importer.textureType = TextureImporterType.Sprite;
            importer.spriteImportMode = SpriteImportMode.Single;
            bool qr = assetPath.EndsWith("stage-qr.png");
            importer.mipmapEnabled = qr;
            importer.alphaIsTransparency = true;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.filterMode = qr ? FilterMode.Trilinear : FilterMode.Bilinear;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.npotScale = TextureImporterNPOTScale.None;
            importer.maxTextureSize = 2048;

            TextureImporterSettings settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.spriteMeshType = SpriteMeshType.FullRect;
            settings.spritePixelsPerUnit = 100f;
            settings.spriteBorder = BorderFor(assetPath);
            importer.SetTextureSettings(settings);
        }

        /// <summary>Corte en 9 (izquierda, abajo, derecha, arriba) de cada forma.</summary>
        private static Vector4 BorderFor(string path)
        {
            if (path.EndsWith("stage-round.png"))
            {
                return new Vector4(64f, 64f, 64f, 64f);
            }

            if (path.EndsWith("stage-shadow.png"))
            {
                return new Vector4(112f, 112f, 112f, 112f);
            }

            return Vector4.zero;
        }

        [MenuItem("Sonia/Reimportar recursos de la pantalla")]
        private static void Reimport()
        {
            AssetDatabase.ImportAsset(Folder.TrimEnd('/'), ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceUpdate);
            Debug.Log("[Sonia] Recursos de la pantalla reimportados (" + Folder + ").");
        }
    }
}
