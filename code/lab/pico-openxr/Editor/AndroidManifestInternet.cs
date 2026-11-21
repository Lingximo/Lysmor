using System.IO;
using System.Text.RegularExpressions;
using UnityEditor.Android;
using UnityEngine;

namespace Companion.Editor
{
    /// <summary>在 Gradle 工程生成后补 INTERNET 权限，避免自定义 manifest 覆盖 Unity activity。</summary>
    public class AndroidManifestInternet : IPostGenerateGradleAndroidProject
    {
        public int callbackOrder => 1000;

        public void OnPostGenerateGradleAndroidProject(string path)
        {
            var manifest = Path.Combine(path, "src/main/AndroidManifest.xml");
            if (!File.Exists(manifest)) return;
            var text = File.ReadAllText(manifest);
            text = Regex.Replace(text, @"\s*<uses-permission android:name=""android.permission.INTERNET""\s*/>", "");
            text = Regex.Replace(text, @"\s*<uses-permission android:name=""android.permission.CAMERA""\s*/>", "");
            var m = Regex.Match(text, @"<manifest[^>]*>");
            if (!m.Success)
            {
                Debug.LogError("AndroidManifestInternet: no <manifest> tag");
                return;
            }
            text = text.Insert(m.Index + m.Length, "\n  <uses-permission android:name=\"android.permission.INTERNET\" />\n  <uses-permission android:name=\"android.permission.CAMERA\" />");

            // PICO 系统透视开关：老版 manifest 里就有这两个 meta-data，新版缺失会黑屏。
            text = Regex.Replace(text, @"\s*<meta-data android:name=""enable_vst""[^/]*/>", "");
            text = Regex.Replace(text, @"\s*<meta-data android:name=""enable_mr_safeguard""[^/]*/>", "");
            var app = Regex.Match(text, @"<application[^>]*>");
            if (app.Success)
            {
                text = text.Insert(app.Index + app.Length,
                    "\n    <meta-data android:name=\"enable_vst\" android:value=\"1\" />" +
                    "\n    <meta-data android:name=\"enable_mr_safeguard\" android:value=\"0\" />");
            }
            File.WriteAllText(manifest, text);
            Debug.Log("AndroidManifestInternet: added INTERNET + enable_vst");
        }
    }
}
