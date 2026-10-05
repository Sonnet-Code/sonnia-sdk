// Puente del llavero para la app de macOS: cero llavero.
//
// Las librerías nativas de Genies (libGeniesAuthAPI, libGeniesTelemetryBridge)
// guardan sus tokens en el llavero de macOS con SecItemAdd y compañía. Con la app
// firmada solo en local, macOS pide la contraseña del llavero una y otra vez, y
// la app tiene que ser portable: nada guardado en el equipo. Jean: «debe ser
// totalmente portable, 0 keychain».
//
// El post-proceso de la build (SoniaPlayerBuildFixes) cambia en esas librerías la
// dependencia de Security.framework por este puente. Aquí van SecItemAdd,
// SecItemCopyMatching, SecItemUpdate y SecItemDelete sobre un almacén en memoria
// (servicio + cuenta -> datos), y el resto de Security (las constantes kSec...)
// se reexporta tal cual. Al cerrar la app no queda nada: cada arranque hace un
// registro anónimo nuevo en Genies.

#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <pthread.h>
#include <stdlib.h>

// Elementos guardados: "servicio\ncuenta" -> datos.
static CFMutableDictionaryRef g_items;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;

static CFMutableDictionaryRef Items(void)
{
    if (g_items == NULL)
    {
        g_items = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    }

    return g_items;
}

static CFStringRef Attribute(CFDictionaryRef query, CFStringRef name)
{
    CFTypeRef value = query != NULL ? CFDictionaryGetValue(query, name) : NULL;
    return value != NULL && CFGetTypeID(value) == CFStringGetTypeID() ? (CFStringRef)value : NULL;
}

static CFStringRef ItemKey(CFStringRef service, CFStringRef account)
{
    return CFStringCreateWithFormat(NULL, NULL, CFSTR("%@\n%@"),
                                    service != NULL ? service : CFSTR(""),
                                    account != NULL ? account : CFSTR(""));
}

// Claves que casan con la consulta: la del servicio y la cuenta, o todas las del
// servicio si la consulta no trae cuenta. Hay que llamarla con el cerrojo puesto.
static CFArrayRef Matches(CFDictionaryRef query)
{
    CFStringRef service = Attribute(query, kSecAttrService);
    CFStringRef account = Attribute(query, kSecAttrAccount);
    CFMutableArrayRef keys = CFArrayCreateMutable(NULL, 0, &kCFTypeArrayCallBacks);
    if (account != NULL)
    {
        CFStringRef key = ItemKey(service, account);
        if (CFDictionaryContainsKey(Items(), key))
        {
            CFArrayAppendValue(keys, key);
        }

        CFRelease(key);
        return keys;
    }

    CFStringRef prefix = ItemKey(service, NULL);
    CFIndex count = CFDictionaryGetCount(Items());
    if (count > 0)
    {
        const void **all = (const void **)malloc(sizeof(void *) * (size_t)count);
        CFDictionaryGetKeysAndValues(Items(), all, NULL);
        for (CFIndex i = 0; i < count; i++)
        {
            if (CFStringHasPrefix((CFStringRef)all[i], prefix))
            {
                CFArrayAppendValue(keys, all[i]);
            }
        }

        free(all);
    }

    CFRelease(prefix);
    return keys;
}

static CFDataRef ValueData(CFDictionaryRef attributes)
{
    CFTypeRef data = attributes != NULL ? CFDictionaryGetValue(attributes, kSecValueData) : NULL;
    return data != NULL && CFGetTypeID(data) == CFDataGetTypeID() ? (CFDataRef)data : NULL;
}

OSStatus SecItemAdd(CFDictionaryRef attributes, CFTypeRef *result)
{
    if (result != NULL)
    {
        *result = NULL;
    }

    CFDataRef data = ValueData(attributes);
    CFStringRef key = ItemKey(Attribute(attributes, kSecAttrService), Attribute(attributes, kSecAttrAccount));
    OSStatus status = errSecSuccess;
    pthread_mutex_lock(&g_lock);
    if (CFDictionaryContainsKey(Items(), key))
    {
        status = errSecDuplicateItem;
    }
    else
    {
        CFDataRef copy = data != NULL ? CFDataCreateCopy(NULL, data) : CFDataCreate(NULL, NULL, 0);
        CFDictionarySetValue(Items(), key, copy);
        CFRelease(copy);
    }

    pthread_mutex_unlock(&g_lock);
    CFRelease(key);
    return status;
}

OSStatus SecItemCopyMatching(CFDictionaryRef query, CFTypeRef *result)
{
    if (result != NULL)
    {
        *result = NULL;
    }

    OSStatus status = errSecItemNotFound;
    pthread_mutex_lock(&g_lock);
    CFArrayRef keys = Matches(query);
    if (CFArrayGetCount(keys) > 0)
    {
        status = errSecSuccess;
        CFTypeRef wantsData = CFDictionaryGetValue(query, kSecReturnData);
        if (result != NULL && wantsData != NULL && CFEqual(wantsData, kCFBooleanTrue))
        {
            CFDataRef data = (CFDataRef)CFDictionaryGetValue(Items(), CFArrayGetValueAtIndex(keys, 0));
            *result = CFDataCreateCopy(NULL, data);
        }
    }

    CFRelease(keys);
    pthread_mutex_unlock(&g_lock);
    return status;
}

OSStatus SecItemUpdate(CFDictionaryRef query, CFDictionaryRef attributesToUpdate)
{
    CFDataRef data = ValueData(attributesToUpdate);
    OSStatus status = errSecItemNotFound;
    pthread_mutex_lock(&g_lock);
    CFArrayRef keys = Matches(query);
    CFIndex count = CFArrayGetCount(keys);
    if (count > 0)
    {
        status = errSecSuccess;
        for (CFIndex i = 0; data != NULL && i < count; i++)
        {
            CFDataRef copy = CFDataCreateCopy(NULL, data);
            CFDictionarySetValue(Items(), CFArrayGetValueAtIndex(keys, i), copy);
            CFRelease(copy);
        }
    }

    CFRelease(keys);
    pthread_mutex_unlock(&g_lock);
    return status;
}

OSStatus SecItemDelete(CFDictionaryRef query)
{
    OSStatus status = errSecItemNotFound;
    pthread_mutex_lock(&g_lock);
    CFArrayRef keys = Matches(query);
    CFIndex count = CFArrayGetCount(keys);
    for (CFIndex i = 0; i < count; i++)
    {
        CFDictionaryRemoveValue(Items(), CFArrayGetValueAtIndex(keys, i));
        status = errSecSuccess;
    }

    CFRelease(keys);
    pthread_mutex_unlock(&g_lock);
    return status;
}
