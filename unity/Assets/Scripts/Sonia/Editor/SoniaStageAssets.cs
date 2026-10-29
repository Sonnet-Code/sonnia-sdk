// Import settings for the screen assets (Resources/Stage): sprites without
// mipmaps or compression so edges and the background gradient stay clean,
// with 9-slice borders for the rounded shapes and the shadow.

using UnityEditor;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Sets up the PNGs in Resources/Stage the way StageScreen expects them.</summary>
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
            importer.mipmapEnabled = false;
            importer.alphaIsTransparency = true;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.filterMode = FilterMode.Bilinear;
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

        /// <summary>9-slice border (left, bottom, right, top) of each shape.</summary>
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

        [MenuItem("Sonnia/Reimport Screen Assets")]
        private static void Reimport()
        {
            AssetDatabase.ImportAsset(Folder.TrimEnd('/'), ImportAssetOptions.ImportRecursive | ImportAssetOptions.ForceUpdate);
            Debug.Log("[Sonnia] Screen assets reimported (" + Folder + ").");
        }
    }
}
