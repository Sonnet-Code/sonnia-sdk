// Puente para el plugin NAF de Genies en la app de macOS.
//
// Unity precarga al arrancar los plugins nativos que importa el código C#, antes
// de crear el dispositivo Metal. El UnityPluginLoad de libgnUnityPlugin (NAF)
// crea ahí una cola de Metal y, sin dispositivo, lanza
// "Failed to create Metal command queue" y tumba la app. En el editor no pasa
// porque el dispositivo ya existe cuando se carga.
//
// El post-proceso de la build (SoniaMacBuildFixes) renombra el plugin real a
// libgnUnityPluginReal.dylib y pone este puente con el nombre original. El
// puente reexporta todos los símbolos del real (las P/Invoke de Genies llegan
// a él sin cambios), pero su propio UnityPluginLoad solo guarda las interfaces
// de Unity y espera: cuando existe el MTLDevice, llama al UnityPluginLoad del
// real, como habría hecho Unity.

#import <Metal/Metal.h>

#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

#include "IUnityGraphics.h"
#include "IUnityGraphicsMetal.h"
#include "IUnityInterface.h"

typedef void(UNITY_INTERFACE_API* PluginLoadFn)(IUnityInterfaces*);
typedef void(UNITY_INTERFACE_API* PluginUnloadFn)();

static IUnityInterfaces* s_interfaces = nullptr;
static IUnityGraphics* s_graphics = nullptr;
static bool s_loaded = false;
static bool s_waiting = false;
static PluginUnloadFn s_realUnload = nullptr;

static void Log(const char* text)
{
    fprintf(stderr, "[SoniaNafShim] %s\n", text);
    fflush(stderr);
}

// El plugin real ya está cargado (es una dependencia reexportada): se busca su
// UnityPluginLoad en su propia imagen, no en la del puente.
static void* RealImage()
{
    Dl_info info;
    if (dladdr((void*)&RealImage, &info) == 0 || info.dli_fname == nullptr)
    {
        return nullptr;
    }
    char self[PATH_MAX];
    strncpy(self, info.dli_fname, sizeof(self) - 1);
    self[sizeof(self) - 1] = 0;
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/libgnUnityPluginReal.dylib", dirname(self));
    return dlopen(path, RTLD_NOW | RTLD_NOLOAD);
}

static void LoadReal()
{
    if (s_loaded)
    {
        return;
    }
    s_loaded = true;
    void* real = RealImage();
    if (real == nullptr)
    {
        Log("no encuentro libgnUnityPluginReal.dylib");
        return;
    }
    PluginLoadFn load = (PluginLoadFn)dlsym(real, "UnityPluginLoad");
    s_realUnload = (PluginUnloadFn)dlsym(real, "UnityPluginUnload");
    if (load == nullptr)
    {
        Log("el plugin real no tiene UnityPluginLoad");
        return;
    }
    Log("MTLDevice listo: inicializo NAF");
    load(s_interfaces);
}

// El evento de dispositivo llega antes de que Unity tenga el MTLDevice: se
// comprueba cada 100 ms en la cola principal y se inicializa NAF cuando existe.
static void LoadWhenMetalReady(int attempt)
{
    IUnityGraphicsMetal* metal = s_interfaces->Get<IUnityGraphicsMetal>();
    if (metal != nullptr && metal->MetalDevice() != nil)
    {
        LoadReal();
        return;
    }
    if (attempt >= 300)
    {
        Log("sin MTLDevice tras 30 s: NAF no se inicializa");
        return;
    }
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        LoadWhenMetalReady(attempt + 1);
    });
}

static void UNITY_INTERFACE_API OnGraphicsDeviceEvent(UnityGfxDeviceEventType eventType)
{
    if (eventType == kUnityGfxDeviceEventInitialize && !s_waiting && !s_loaded)
    {
        s_waiting = true;
        dispatch_async(dispatch_get_main_queue(), ^{
            LoadWhenMetalReady(0);
        });
    }
}

extern "C" void UNITY_INTERFACE_EXPORT UNITY_INTERFACE_API UnityPluginLoad(IUnityInterfaces* interfaces)
{
    s_interfaces = interfaces;
    s_graphics = interfaces->Get<IUnityGraphics>();
    Log("esperando al dispositivo gráfico");
    s_graphics->RegisterDeviceEventCallback(OnGraphicsDeviceEvent);
    if (s_graphics->GetRenderer() != kUnityGfxRendererNull)
    {
        OnGraphicsDeviceEvent(kUnityGfxDeviceEventInitialize);
    }
}

extern "C" void UNITY_INTERFACE_EXPORT UNITY_INTERFACE_API UnityPluginUnload()
{
    if (s_graphics != nullptr)
    {
        s_graphics->UnregisterDeviceEventCallback(OnGraphicsDeviceEvent);
    }
    if (s_realUnload != nullptr)
    {
        s_realUnload();
    }
}
