#include <windows.h>
#include <audioclient.h>
#include <mmdeviceapi.h>
#include <iostream>
#include <vector>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <chrono>
#include <algorithm>
#include <cwctype>
#include <string>
#include <cstdlib>
#include <propsys.h>

// Formatos soportados por WASAPI
#ifndef WAVE_FORMAT_IEEE_FLOAT
#define WAVE_FORMAT_IEEE_FLOAT 0x0003
#endif

// DEFINE GUIDS para WASAPI
const CLSID CLSID_MMDeviceEnumerator = __uuidof(MMDeviceEnumerator);
const IID IID_IMMDeviceEnumerator = __uuidof(IMMDeviceEnumerator);
const IID IID_IAudioClient = __uuidof(IAudioClient);
const IID IID_IAudioCaptureClient = __uuidof(IAudioCaptureClient);

// Definición manual de GUIDs para evitar errores de enlazado en MinGW
const GUID KSDATAFORMAT_SUBTYPE_PCM = { 0x00000001, 0x0000, 0x0010, { 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71 } };
const GUID KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = { 0x00000003, 0x0000, 0x0010, { 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71 } };
// PKEY_Device_FriendlyName (functiondiscoverykeys_devp.h is not shipped by
// the MinGW SDK used by compile_audio.bat).
const PROPERTYKEY PKEY_Device_FriendlyName = {
    { 0xa45c254e, 0xdf1c, 0x4efd, { 0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0 } },
    14
};

std::wstring g_selectedDeviceName;

namespace {

std::wstring Lowercase(std::wstring value) {
    std::transform(value.begin(), value.end(), value.begin(),
        [](wchar_t character) { return std::towlower(character); });
    return value;
}

bool ContainsAny(const std::wstring& value, const std::initializer_list<const wchar_t*>& terms) {
    for (const wchar_t* term : terms) {
        if (value.find(term) != std::wstring::npos) return true;
    }
    return false;
}

std::wstring GetFriendlyName(IMMDevice* device) {
    if (!device) return L"";

    IPropertyStore* propertyStore = nullptr;
    if (FAILED(device->OpenPropertyStore(STGM_READ, &propertyStore))) return L"";

    PROPVARIANT value;
    PropVariantInit(&value);
    std::wstring name;
    if (SUCCEEDED(propertyStore->GetValue(PKEY_Device_FriendlyName, &value)) &&
        value.vt == VT_LPWSTR && value.pwszVal) {
        name = value.pwszVal;
    }
    PropVariantClear(&value);
    propertyStore->Release();
    return name;
}

bool LooksLikePhysicalMicrophone(const std::wstring& friendlyName) {
    const std::wstring name = Lowercase(friendlyName);
    const bool isLoopback = ContainsAny(name, {
        L"mezcla estéreo", L"mezcla estereo", L"stereo mix", L"loopback", L"cable output"
    });
    const bool isMicrophone = ContainsAny(name, {
        L"micrófono", L"microfono", L"microphone", L"mic input", L"micrófonos", L"microfonos"
    });
    return isMicrophone && !isLoopback;
}

IMMDevice* SelectCaptureDevice(IMMDeviceEnumerator* enumerator) {
    if (!enumerator) return nullptr;

    const wchar_t* requestedName = _wgetenv(L"ICARO_AUDIO_DEVICE");
    const std::wstring requested = requestedName ? Lowercase(requestedName) : L"";

    IMMDevice* defaultDevice = nullptr;
    if (SUCCEEDED(enumerator->GetDefaultAudioEndpoint(eCapture, eConsole, &defaultDevice))) {
        const std::wstring defaultName = GetFriendlyName(defaultDevice);
        const std::wstring normalizedDefault = Lowercase(defaultName);
        if (!requested.empty() && normalizedDefault.find(requested) != std::wstring::npos) {
            g_selectedDeviceName = defaultName;
            return defaultDevice;
        }
        if (requested.empty() && LooksLikePhysicalMicrophone(defaultName)) {
            g_selectedDeviceName = defaultName;
            return defaultDevice;
        }
    }

    IMMDeviceCollection* devices = nullptr;
    if (FAILED(enumerator->EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE, &devices))) {
        return defaultDevice;
    }

    UINT count = 0;
    devices->GetCount(&count);
    IMMDevice* selectedDevice = nullptr;
    for (UINT index = 0; index < count; ++index) {
        IMMDevice* candidate = nullptr;
        if (FAILED(devices->Item(index, &candidate))) continue;

        const std::wstring name = GetFriendlyName(candidate);
        const std::wstring normalizedName = Lowercase(name);
        const bool matchesRequested = !requested.empty() &&
            normalizedName.find(requested) != std::wstring::npos;
        const bool isPreferred = requested.empty() && LooksLikePhysicalMicrophone(name);
        if (matchesRequested || isPreferred) {
            g_selectedDeviceName = name;
            selectedDevice = candidate;
            break;
        }
        candidate->Release();
    }
    devices->Release();

    if (selectedDevice) {
        if (defaultDevice) defaultDevice->Release();
        return selectedDevice;
    }
    g_selectedDeviceName = defaultDevice ? GetFriendlyName(defaultDevice) : L"";
    return defaultDevice;
}

}

// Resultados de Inicialización
enum AudioInitResult
{
    AUDIO_INIT_OK = 0,
    AUDIO_INIT_DEVICE_NOT_FOUND = 1,
    AUDIO_INIT_ACCESS_DENIED = 2,
    AUDIO_INIT_UNSUPPORTED_FORMAT = 3,
    AUDIO_INIT_FAILED = 4
};

// Resultados de Lectura
enum AudioReadResult
{
    AUDIO_READ_OK = 0,
    AUDIO_READ_TIMEOUT = 1,
    AUDIO_READ_STOPPED = 2,
    AUDIO_READ_ERROR = 3
};

// Estadísticas de Audio
struct AudioStats
{
    int droppedFrames;
    int overruns;
    int underruns;
    float latencyMs;
    float bufferUsage;
    int sampleRate;
};

// ============================================================================
// CLASE RESAMPLER (Lineal Inicial, TODO: Migrar a SpeexDSP)
// ============================================================================
class AudioResampler {
public:
    AudioResampler(int inputSampleRate, int inputChannels, WORD inputFormatTag, WORD inputBitsPerSample)
        : sr_in_(inputSampleRate), channels_(inputChannels), format_tag_(inputFormatTag),
          bits_per_sample_(inputBitsPerSample), source_time_(0.0) {}

    void Process(const BYTE* pData, UINT32 numFrames, std::vector<int16_t>& outSamples) {
        if (numFrames == 0) return;

        // 1. Convertir buffer de entrada a un array float continuo de muestras Mono
        std::vector<float> monoFloatSamples;
        monoFloatSamples.reserve(numFrames);

        if (pData == nullptr) {
            // WASAPI marks silent packets without guaranteeing valid pData.
            monoFloatSamples.assign(numFrames, 0.0f);
        } else if (format_tag_ == WAVE_FORMAT_IEEE_FLOAT) {
            const float* floatData = reinterpret_cast<const float*>(pData);
            for (UINT32 f = 0; f < numFrames; ++f) {
                float sum = 0.0f;
                for (int c = 0; c < channels_; ++c) {
                    sum += floatData[f * channels_ + c];
                }
                monoFloatSamples.push_back(sum / channels_);
            }
        } else if (format_tag_ == WAVE_FORMAT_PCM) {
            const int bytesPerSample = (bits_per_sample_ + 7) / 8;
            const BYTE* pcmData = pData;
            for (UINT32 f = 0; f < numFrames; ++f) {
                float sum = 0.0f;
                for (int c = 0; c < channels_; ++c) {
                    const BYTE* sample = pcmData + (f * channels_ + c) * bytesPerSample;
                    float normalized = 0.0f;
                    if (bits_per_sample_ == 8) {
                        normalized = (static_cast<int>(*sample) - 128) / 128.0f;
                    } else if (bits_per_sample_ == 16) {
                        const int16_t value = static_cast<int16_t>(sample[0] | (sample[1] << 8));
                        normalized = static_cast<float>(value) / 32768.0f;
                    } else if (bits_per_sample_ == 24) {
                        int32_t value = sample[0] | (sample[1] << 8) | (sample[2] << 16);
                        if (value & 0x00800000) value |= 0xff000000;
                        normalized = static_cast<float>(value) / 8388608.0f;
                    } else if (bits_per_sample_ >= 32) {
                        const int32_t value = static_cast<int32_t>(sample[0] |
                            (sample[1] << 8) | (sample[2] << 16) | (sample[3] << 24));
                        normalized = static_cast<float>(value) / 2147483648.0f;
                    }
                    sum += normalized;
                }
                monoFloatSamples.push_back(sum / channels_);
            }
        } else {
            monoFloatSamples.assign(numFrames, 0.0f);
        }

        // 2. Linear Resampling de sr_in_ a 16000
        double step = (double)sr_in_ / 16000.0;
        
        // Agregar nuevas muestras al historial
        history_.insert(history_.end(), monoFloatSamples.begin(), monoFloatSamples.end());

        size_t totalSamples = history_.size();
        if (totalSamples < 2) return;

        while (true) {
            double next_idx = source_time_;
            int idx1 = (int)next_idx;
            int idx2 = idx1 + 1;

            if (idx2 >= totalSamples) {
                break;
            }

            double frac = next_idx - idx1;
            float val = (1.0f - frac) * history_[idx1] + frac * history_[idx2];

            // Limitador / Clamping a int16_t
            if (val > 1.0f) val = 1.0f;
            if (val < -1.0f) val = -1.0f;
            outSamples.push_back(static_cast<int16_t>(val * 32767.f));

            source_time_ += step;
        }

        // Mantener sobrantes en historial
        int consumed = (int)source_time_;
        if (consumed > 0) {
            history_.erase(history_.begin(), history_.begin() + consumed);
            source_time_ -= consumed;
        }
    }

    void Reset() {
        history_.clear();
        source_time_ = 0.0;
    }

private:
    int sr_in_;
    int channels_;
    WORD format_tag_;
    WORD bits_per_sample_;
    double source_time_;
    std::vector<float> history_;
};

// ============================================================================
// CLASE RING BUFFER
// ============================================================================
class RingBuffer {
public:
    RingBuffer(size_t capacity) : capacity_(capacity), buffer_(capacity), head_(0), tail_(0), size_(0) {}

    void Write(const int16_t* data, size_t count, int& overruns) {
        std::unique_lock<std::mutex> lock(mutex_);
        for (size_t i = 0; i < count; ++i) {
            buffer_[head_] = data[i];
            head_ = (head_ + 1) % capacity_;
            if (size_ == capacity_) {
                tail_ = (tail_ + 1) % capacity_; // Sobrescribir más viejo
                overruns++;
            } else {
                size_++;
            }
        }
        cond_.notify_all();
    }

    bool Read(int16_t* out_data, size_t count, int timeout_ms, std::atomic<bool>& stopped, int& underruns) {
        std::unique_lock<std::mutex> lock(mutex_);
        auto timeout_time = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);

        while (size_ < count && !stopped) {
            if (timeout_ms <= 0) {
                cond_.wait(lock);
            } else {
                if (cond_.wait_until(lock, timeout_time) == std::cv_status::timeout) {
                    if (size_ < count) {
                        underruns++;
                        return false;
                    }
                    break;
                }
            }
        }

        if (stopped && size_ < count) {
            return false;
        }

        for (size_t i = 0; i < count; ++i) {
            out_data[i] = buffer_[tail_];
            tail_ = (tail_ + 1) % capacity_;
        }
        size_ -= count;
        return true;
    }

    void Clear() {
        std::unique_lock<std::mutex> lock(mutex_);
        head_ = 0;
        tail_ = 0;
        size_ = 0;
        cond_.notify_all();
    }

    float GetUsagePercentage() {
        std::unique_lock<std::mutex> lock(mutex_);
        return ((float)size_ / capacity_) * 100.0f;
    }

    void NotifyAll() {
        std::unique_lock<std::mutex> lock(mutex_);
        cond_.notify_all();
    }

private:
    size_t capacity_;
    std::vector<int16_t> buffer_;
    size_t head_;
    size_t tail_;
    size_t size_;
    mutable std::mutex mutex_;
    std::condition_variable cond_;
};

// ============================================================================
// VARIABLES GLOBALES
// ============================================================================
std::thread g_captureThread;
std::atomic<bool> g_running(false);
std::atomic<bool> g_stopped(false);
RingBuffer g_ringBuffer(32000); // 2 segundos de buffer a 16000Hz (64KB)

// Estadísticas
std::atomic<int> g_droppedFrames(0);
std::atomic<int> g_overruns(0);
std::atomic<int> g_underruns(0);
float g_latencyMs = 0.0f;
int g_deviceSampleRate = 16000;

// ============================================================================
// EXPORTACIÓN DE FUNCIONES DE LA DLL
// ============================================================================
extern "C" {

    __declspec(dllexport) AudioInitResult IcaroAudio_Start() {
        if (g_running) {
            return AUDIO_INIT_OK;
        }

        g_stopped = false;
        g_ringBuffer.Clear();
        g_droppedFrames = 0;
        g_overruns = 0;
        g_underruns = 0;

        // Inicializar COM
        HRESULT hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
        const bool comInitialized = SUCCEEDED(hr);
        if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) {
            return AUDIO_INIT_FAILED;
        }

        IMMDeviceEnumerator* pEnumerator = NULL;
        hr = CoCreateInstance(CLSID_MMDeviceEnumerator, NULL, CLSCTX_ALL, IID_IMMDeviceEnumerator, (void**)&pEnumerator);
        if (FAILED(hr)) {
            if (comInitialized) CoUninitialize();
            return AUDIO_INIT_FAILED;
        }

        IMMDevice* pDevice = SelectCaptureDevice(pEnumerator);
        hr = pDevice ? S_OK : E_NOTFOUND;
        if (FAILED(hr)) {
            pEnumerator->Release();
            if (comInitialized) CoUninitialize();
            if (hr == HRESULT_FROM_WIN32(ERROR_NOT_FOUND) || hr == HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND) || hr == 0x80070490) {
                return AUDIO_INIT_DEVICE_NOT_FOUND;
            }
            return AUDIO_INIT_FAILED;
        }
        pEnumerator->Release();

        IAudioClient* pAudioClient = NULL;
        hr = pDevice->Activate(IID_IAudioClient, CLSCTX_ALL, NULL, (void**)&pAudioClient);
        pDevice->Release();
        if (FAILED(hr)) {
            if (comInitialized) CoUninitialize();
            if (hr == E_ACCESSDENIED) {
                return AUDIO_INIT_ACCESS_DENIED;
            }
            return AUDIO_INIT_FAILED;
        }

        WAVEFORMATEX* pwfx = NULL;
        hr = pAudioClient->GetMixFormat(&pwfx);
        if (FAILED(hr)) {
            pAudioClient->Release();
            if (comInitialized) CoUninitialize();
            return AUDIO_INIT_FAILED;
        }

        WORD format_tag = pwfx->wFormatTag;
        if (format_tag == WAVE_FORMAT_EXTENSIBLE) {
            WAVEFORMATEXTENSIBLE* pEx = reinterpret_cast<WAVEFORMATEXTENSIBLE*>(pwfx);
            if (pEx->SubFormat == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT) {
                format_tag = WAVE_FORMAT_IEEE_FLOAT;
            } else if (pEx->SubFormat == KSDATAFORMAT_SUBTYPE_PCM) {
                format_tag = WAVE_FORMAT_PCM;
            } else {
                CoTaskMemFree(pwfx);
                pAudioClient->Release();
                if (comInitialized) CoUninitialize();
                return AUDIO_INIT_UNSUPPORTED_FORMAT;
            }
        }

        if (format_tag != WAVE_FORMAT_IEEE_FLOAT && format_tag != WAVE_FORMAT_PCM) {
            CoTaskMemFree(pwfx);
            pAudioClient->Release();
            if (comInitialized) CoUninitialize();
            return AUDIO_INIT_UNSUPPORTED_FORMAT;
        }

        g_deviceSampleRate = pwfx->nSamplesPerSec;

        // Inicializar cliente WASAPI
        REFERENCE_TIME hnsRequestedDuration = 1000000; // Buffer de 100ms
        hr = pAudioClient->Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            0,
            hnsRequestedDuration,
            0,
            pwfx,
            NULL
        );

        if (FAILED(hr)) {
            CoTaskMemFree(pwfx);
            pAudioClient->Release();
            if (comInitialized) CoUninitialize();
            if (hr == AUDCLNT_E_UNSUPPORTED_FORMAT) {
                return AUDIO_INIT_UNSUPPORTED_FORMAT;
            }
            return AUDIO_INIT_FAILED;
        }

        // Obtener latencia real
        REFERENCE_TIME latencyTime;
        if (SUCCEEDED(pAudioClient->GetStreamLatency(&latencyTime))) {
            g_latencyMs = (float)latencyTime / 10000.0f;
        } else {
            g_latencyMs = 0.0f;
        }

        IAudioCaptureClient* pCaptureClient = NULL;
        hr = pAudioClient->GetService(IID_IAudioCaptureClient, (void**)&pCaptureClient);
        if (FAILED(hr)) {
            CoTaskMemFree(pwfx);
            pAudioClient->Release();
            if (comInitialized) CoUninitialize();
            return AUDIO_INIT_FAILED;
        }

        // Instanciar resampler
        AudioResampler resampler(pwfx->nSamplesPerSec, pwfx->nChannels, format_tag, pwfx->wBitsPerSample);
        CoTaskMemFree(pwfx);

        hr = pAudioClient->Start();
        if (FAILED(hr)) {
            pCaptureClient->Release();
            pAudioClient->Release();
            if (comInitialized) CoUninitialize();
            return AUDIO_INIT_FAILED;
        }

        g_running = true;

        g_captureThread = std::thread([pAudioClient, pCaptureClient, resampler]() mutable {
            const bool threadComInitialized = SUCCEEDED(CoInitializeEx(NULL, COINIT_MULTITHREADED));
            HRESULT hr;
            while (g_running) {
                std::this_thread::sleep_for(std::chrono::milliseconds(20)); // Frecuencia de muestreo periódica

                UINT32 packetLength = 0;
                hr = pCaptureClient->GetNextPacketSize(&packetLength);
                if (FAILED(hr)) continue;

                while (packetLength > 0 && g_running) {
                    BYTE* pData;
                    UINT32 numFramesAvailable;
                    DWORD flags;
                    
                    hr = pCaptureClient->GetBuffer(&pData, &numFramesAvailable, &flags, NULL, NULL);
                    if (SUCCEEDED(hr)) {
                        if (flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) {
                            g_droppedFrames++;
                            resampler.Reset();
                        }

                        if (numFramesAvailable > 0) {
                            std::vector<int16_t> targetSamples;
                            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                                resampler.Process(nullptr, numFramesAvailable, targetSamples);
                            } else {
                                resampler.Process(pData, numFramesAvailable, targetSamples);
                            }
                            if (!targetSamples.empty()) {
                                int overruns = 0;
                                g_ringBuffer.Write(targetSamples.data(), targetSamples.size(), overruns);
                                if (overruns > 0) {
                                    g_overruns += overruns;
                                }
                            }
                        }
                        pCaptureClient->ReleaseBuffer(numFramesAvailable);
                    }

                    hr = pCaptureClient->GetNextPacketSize(&packetLength);
                    if (FAILED(hr)) break;
                }
            }

            pAudioClient->Stop();
            pCaptureClient->Release();
            pAudioClient->Release();
            if (threadComInitialized) CoUninitialize();
        });

        // COM is initialized per thread. The setup thread must release only
        // its own initialization; the capture thread owns its COM lifetime.
        if (comInitialized) CoUninitialize();

        return AUDIO_INIT_OK;
    }

    __declspec(dllexport) void IcaroAudio_Stop() {
        if (!g_running) return;

        g_running = false;
        g_stopped = true;

        // Desbloquear hilos bloqueados en Read
        g_ringBuffer.NotifyAll();

        if (g_captureThread.joinable()) {
            g_captureThread.join();
        }
    }

    __declspec(dllexport) AudioReadResult IcaroAudio_Read(int16_t* buffer, int samples, int timeout_ms) {
        if (g_stopped) {
            return AUDIO_READ_STOPPED;
        }

        int underruns = 0;
        bool success = g_ringBuffer.Read(buffer, samples, timeout_ms, g_stopped, underruns);
        if (underruns > 0) {
            g_underruns += underruns;
        }

        if (g_stopped) {
            return AUDIO_READ_STOPPED;
        }
        if (!success) {
            return AUDIO_READ_TIMEOUT;
        }
        return AUDIO_READ_OK;
    }

    __declspec(dllexport) void IcaroAudio_GetStats(AudioStats* outStats) {
        if (!outStats) return;
        outStats->droppedFrames = g_droppedFrames.load();
        outStats->overruns = g_overruns.load();
        outStats->underruns = g_underruns.load();
        outStats->latencyMs = g_latencyMs;
        outStats->bufferUsage = g_ringBuffer.GetUsagePercentage();
        outStats->sampleRate = 16000;
    }

    __declspec(dllexport) const wchar_t* IcaroAudio_GetDeviceName() {
        return g_selectedDeviceName.c_str();
    }
}
