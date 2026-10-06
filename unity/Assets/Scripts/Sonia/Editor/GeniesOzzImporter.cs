// Importa los .ozz de Genies (gestos del chat de Genies) como GeniesOzzAsset:
// los bytes tal cual, que GeniesGestureLayer decodifica en tiempo de ejecución.
// Así en el repo solo están los archivos originales del CDN de Genies.

using System.IO;
using UnityEditor.AssetImporters;
using UnityEngine;

namespace Sonia.EditorTools
{
    /// <summary>Importador de clips OZZ de Genies.</summary>
    [ScriptedImporter(1, "ozz")]
    public sealed class GeniesOzzImporter : ScriptedImporter
    {
        public override void OnImportAsset(AssetImportContext ctx)
        {
            GeniesOzzAsset asset = ScriptableObject.CreateInstance<GeniesOzzAsset>();
            asset.name = Path.GetFileNameWithoutExtension(ctx.assetPath);
            asset.SetData(File.ReadAllBytes(ctx.assetPath));
            ctx.AddObjectToAsset("ozz", asset);
            ctx.SetMainObject(asset);
        }
    }
}
