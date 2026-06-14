#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>
#include <d3d11.h>
#include <d3dcompiler.h>
#include <dcomp.h>
#include <dwmapi.h>
#include <dxgi1_2.h>
#include <wrl/client.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace
{
constexpr DWORD kWdaExcludeFromCapture = 0x00000011;
constexpr int kHotkeyId = 0x4550;
constexpr double kRampUpSeconds = 45.0;
constexpr double kRampDownSeconds = 0.3;
constexpr float kMaxDimAmount = 0.32f;
constexpr const wchar_t* kWindowClassName = L"EchoPostureBlurOverlayHost";

enum class CaptureMode
{
    None,
    DesktopDuplication,
    Gdi,
    SystemBackdrop
};

struct AccentPolicy
{
    int accent_state;
    int accent_flags;
    DWORD gradient_color;
    int animation_id;
};

struct WindowCompositionAttributeData
{
    int attribute;
    void* data;
    SIZE_T size_of_data;
};

using SetWindowCompositionAttributeFn = BOOL(WINAPI*)(HWND, WindowCompositionAttributeData*);

constexpr int kWcaAccentPolicy = 19;
constexpr int kAccentDisabled = 0;
constexpr int kAccentEnableTransparentGradient = 2;
constexpr int kAccentEnableBlurBehind = 3;
constexpr int kAccentEnableAcrylicBlurBehind = 4;

struct ShaderParams
{
    float texel_x;
    float texel_y;
    float radius;
    float level;
    float dim_amount;
    float output_w;
    float output_h;
    float marker;
};

static_assert(sizeof(ShaderParams) == 32, "Shader constant buffer must stay 16-byte aligned.");

std::string JsonEscape(const std::string& value)
{
    std::ostringstream output;
    for (char ch : value)
    {
        switch (ch)
        {
        case '\\':
            output << "\\\\";
            break;
        case '"':
            output << "\\\"";
            break;
        case '\n':
            output << "\\n";
            break;
        case '\r':
            output << "\\r";
            break;
        case '\t':
            output << "\\t";
            break;
        default:
            output << ch;
            break;
        }
    }
    return output.str();
}

std::string HrToString(HRESULT hr)
{
    std::ostringstream output;
    output << "HRESULT 0x" << std::hex << static_cast<unsigned long>(hr);
    return output.str();
}

bool ExtractJsonFloat(const std::string& line, const char* key, float& value)
{
    std::string needle = "\"";
    needle += key;
    needle += "\":";
    size_t pos = line.find(needle);
    if (pos == std::string::npos)
    {
        return false;
    }

    pos += needle.size();
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos])))
    {
        ++pos;
    }

    char* end = nullptr;
    float parsed = std::strtof(line.c_str() + pos, &end);
    if (end == line.c_str() + pos)
    {
        return false;
    }

    value = parsed;
    return true;
}

bool IsWindows10_2004OrNewer()
{
    using RtlGetVersionFn = LONG(WINAPI*)(PRTL_OSVERSIONINFOW);
    HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    if (!ntdll)
    {
        return false;
    }

    auto rtl_get_version = reinterpret_cast<RtlGetVersionFn>(
        GetProcAddress(ntdll, "RtlGetVersion"));
    if (!rtl_get_version)
    {
        return false;
    }

    RTL_OSVERSIONINFOW version = {};
    version.dwOSVersionInfoSize = sizeof(version);
    if (rtl_get_version(&version) != 0)
    {
        return false;
    }

    return version.dwMajorVersion > 10 ||
        (version.dwMajorVersion == 10 && version.dwBuildNumber >= 19041);
}

LRESULT CALLBACK OverlayWndProc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_NCHITTEST)
    {
        return HTTRANSPARENT;
    }
    if (message == WM_MOUSEACTIVATE)
    {
        return MA_NOACTIVATE;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

bool RegisterOverlayWindowClass(HINSTANCE instance, std::string& reason)
{
    WNDCLASSEXW wc = {};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = OverlayWndProc;
    wc.hInstance = instance;
    wc.lpszClassName = kWindowClassName;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);

    ATOM atom = RegisterClassExW(&wc);
    if (atom == 0)
    {
        DWORD error = GetLastError();
        if (error != ERROR_CLASS_ALREADY_EXISTS)
        {
            reason = "RegisterClassExW failed";
            return false;
        }
    }
    return true;
}

bool CompileShader(
    const char* source,
    const char* entry,
    const char* target,
    ID3DBlob** blob,
    std::string& reason)
{
    UINT flags = D3DCOMPILE_ENABLE_STRICTNESS;
#if defined(_DEBUG)
    flags |= D3DCOMPILE_DEBUG;
#endif

    ComPtr<ID3DBlob> errors;
    HRESULT hr = D3DCompile(
        source,
        strlen(source),
        nullptr,
        nullptr,
        nullptr,
        entry,
        target,
        flags,
        0,
        blob,
        errors.GetAddressOf());
    if (FAILED(hr))
    {
        reason = "D3DCompile failed: " + HrToString(hr);
        if (errors)
        {
            reason += " ";
            reason += static_cast<const char*>(errors->GetBufferPointer());
        }
        return false;
    }
    return true;
}

const char* kVertexShader = R"(
struct VSOut {
    float4 pos : SV_POSITION;
    float2 uv : TEXCOORD0;
};

VSOut main(uint id : SV_VertexID) {
    float2 pos[3] = {
        float2(-1.0, -1.0),
        float2(-1.0,  3.0),
        float2( 3.0, -1.0)
    };
    float2 uv[3] = {
        float2(0.0, 1.0),
        float2(0.0, -1.0),
        float2(2.0, 1.0)
    };
    VSOut output;
    output.pos = float4(pos[id], 0.0, 1.0);
    output.uv = uv[id];
    return output;
}
)";

const char* kCopyPixelShader = R"(
cbuffer Params : register(b0) {
    float2 texel;
    float radius;
    float level;
    float dim_amount;
    float output_w;
    float output_h;
    float marker;
};
Texture2D input_tex : register(t0);
SamplerState linear_sampler : register(s0);

float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET {
    return input_tex.Sample(linear_sampler, uv);
}
)";

const char* kBlurHPixelShader = R"(
cbuffer Params : register(b0) {
    float2 texel;
    float radius;
    float level;
    float dim_amount;
    float output_w;
    float output_h;
    float marker;
};
Texture2D input_tex : register(t0);
SamplerState linear_sampler : register(s0);

float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET {
    float2 stepv = float2(texel.x * radius, 0.0);
    float4 color = input_tex.Sample(linear_sampler, uv) * 0.204164;
    color += input_tex.Sample(linear_sampler, uv + stepv * 1.0) * 0.180174;
    color += input_tex.Sample(linear_sampler, uv - stepv * 1.0) * 0.180174;
    color += input_tex.Sample(linear_sampler, uv + stepv * 2.0) * 0.123832;
    color += input_tex.Sample(linear_sampler, uv - stepv * 2.0) * 0.123832;
    color += input_tex.Sample(linear_sampler, uv + stepv * 3.0) * 0.066282;
    color += input_tex.Sample(linear_sampler, uv - stepv * 3.0) * 0.066282;
    color += input_tex.Sample(linear_sampler, uv + stepv * 4.0) * 0.027630;
    color += input_tex.Sample(linear_sampler, uv - stepv * 4.0) * 0.027630;
    return color;
}
)";

const char* kBlurVPixelShader = R"(
cbuffer Params : register(b0) {
    float2 texel;
    float radius;
    float level;
    float dim_amount;
    float output_w;
    float output_h;
    float marker;
};
Texture2D input_tex : register(t0);
SamplerState linear_sampler : register(s0);

float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET {
    float2 stepv = float2(0.0, texel.y * radius);
    float4 color = input_tex.Sample(linear_sampler, uv) * 0.204164;
    color += input_tex.Sample(linear_sampler, uv + stepv * 1.0) * 0.180174;
    color += input_tex.Sample(linear_sampler, uv - stepv * 1.0) * 0.180174;
    color += input_tex.Sample(linear_sampler, uv + stepv * 2.0) * 0.123832;
    color += input_tex.Sample(linear_sampler, uv - stepv * 2.0) * 0.123832;
    color += input_tex.Sample(linear_sampler, uv + stepv * 3.0) * 0.066282;
    color += input_tex.Sample(linear_sampler, uv - stepv * 3.0) * 0.066282;
    color += input_tex.Sample(linear_sampler, uv + stepv * 4.0) * 0.027630;
    color += input_tex.Sample(linear_sampler, uv - stepv * 4.0) * 0.027630;
    return color;
}
)";

const char* kCompositePixelShader = R"(
cbuffer Params : register(b0) {
    float2 texel;
    float radius;
    float level;
    float dim_amount;
    float output_w;
    float output_h;
    float marker;
};
Texture2D blurred_tex : register(t0);
Texture2D source_tex : register(t1);
SamplerState linear_sampler : register(s0);

float4 main(float4 pos : SV_POSITION, float2 uv : TEXCOORD0) : SV_TARGET {
    float4 source = source_tex.Sample(linear_sampler, uv);
    float4 blurred = blurred_tex.Sample(linear_sampler, uv);
    float blur_mix = saturate(level);
    float4 color = lerp(source, blurred, blur_mix);
    color.rgb = lerp(color.rgb, float3(0.0, 0.0, 0.0), dim_amount);

    if (marker > 0.5 && pos.x >= 8.0 && pos.x < 12.0 && pos.y >= 8.0 && pos.y < 12.0) {
        return float4(1.0, 0.0, 1.0, 1.0);
    }
    return float4(color.rgb, 1.0);
}
)";

class OutputPipeline
{
public:
    ~OutputPipeline()
    {
        Hide();
        DestroyGdiCaptureResources();
        if (hwnd_)
        {
            DestroyWindow(hwnd_);
            hwnd_ = nullptr;
        }
    }

    bool Initialize(
        HINSTANCE instance,
        IDXGIAdapter1* adapter,
        IDXGIOutput* output,
        std::string& reason)
    {
        instance_ = instance;
        adapter_ = adapter;
        output_ = output;

        HRESULT hr = output_->GetDesc(&output_desc_);
        if (FAILED(hr))
        {
            reason = "IDXGIOutput::GetDesc failed: " + HrToString(hr);
            return false;
        }

        rect_ = output_desc_.DesktopCoordinates;
        width_ = static_cast<UINT>(std::max<LONG>(1, rect_.right - rect_.left));
        height_ = static_cast<UINT>(std::max<LONG>(1, rect_.bottom - rect_.top));
        low_width_ = std::max<UINT>(1, width_ / 4);
        low_height_ = std::max<UINT>(1, height_ / 4);

        if (!CreateDevice(reason) ||
            !CreateWindowAndComposition(reason) ||
            !CreateShaders(reason) ||
            !CreateResources(reason))
        {
            return false;
        }

        std::string duplication_reason;
        if (CreateDuplication(duplication_reason))
        {
            capture_mode_ = CaptureMode::DesktopDuplication;
            return true;
        }

        std::string gdi_reason;
        if (!CreateGdiCaptureResources(gdi_reason))
        {
            reason = duplication_reason + "; GDI capture fallback failed: " + gdi_reason;
            capture_mode_ = CaptureMode::None;
            return false;
        }

        capture_mode_ = CaptureMode::Gdi;
        return true;
    }

    bool SelfCaptureProbe(std::string& reason)
    {
        // Capture once while hidden so the probe frame has real desktop content.
        std::string initial_reason;
        if (!AcquireFrame(100, initial_reason))
        {
            std::string backdrop_reason;
            if (SwitchToSystemBackdrop(backdrop_reason))
            {
                return true;
            }
            reason = "self-capture probe could not acquire initial desktop frame";
            if (!initial_reason.empty())
            {
                reason += ": " + initial_reason;
            }
            if (!backdrop_reason.empty())
            {
                reason += "; system backdrop fallback failed: " + backdrop_reason;
            }
            return false;
        }
        if (!has_frame_)
        {
            reason = "self-capture probe could not acquire initial desktop frame";
            return false;
        }

        Show();
        if (!Render(0.02f, true, reason))
        {
            Hide();
            return false;
        }

        Sleep(120);
        bool marker_seen = false;
        bool capture_ok = DetectMarkerInCapture(marker_seen, reason);
        Hide();

        if (!capture_ok)
        {
            // A timeout means the excluded overlay did not produce a desktop frame, which is acceptable.
            if (reason == "desktop duplication probe timed out")
            {
                return true;
            }
            std::string backdrop_reason;
            if (SwitchToSystemBackdrop(backdrop_reason))
            {
                return true;
            }
            if (!backdrop_reason.empty())
            {
                reason += "; system backdrop fallback failed: " + backdrop_reason;
            }
            return false;
        }

        if (marker_seen)
        {
            reason = "overlay marker appeared in desktop capture";
            return false;
        }

        return true;
    }

    bool Tick(float level, std::string& reason)
    {
        if (level <= 0.001f)
        {
            Hide();
            return true;
        }

        if (capture_mode_ == CaptureMode::SystemBackdrop)
        {
            Show();
            return ApplySystemBackdrop(level, reason);
        }

        if (!AcquireFrame(0, reason))
        {
            std::string backdrop_reason;
            if (SwitchToSystemBackdrop(backdrop_reason))
            {
                Show();
                return ApplySystemBackdrop(level, reason);
            }
            if (!backdrop_reason.empty())
            {
                reason += "; system backdrop fallback failed: " + backdrop_reason;
            }
            return false;
        }

        if (!has_frame_)
        {
            return true;
        }

        Show();
        return Render(level, false, reason);
    }

    void SetVisualConfig(float max_dim_amount, float blur_scale)
    {
        max_dim_amount_ = std::max(0.0f, std::min(0.85f, max_dim_amount));
        blur_scale_ = std::max(0.0f, std::min(1.0f, blur_scale));
    }

    bool HasVariableBlur() const
    {
        return capture_mode_ == CaptureMode::DesktopDuplication ||
            capture_mode_ == CaptureMode::Gdi ||
            capture_mode_ == CaptureMode::SystemBackdrop;
    }

    void Hide()
    {
        if (hwnd_ && visible_)
        {
            ShowWindow(hwnd_, SW_HIDE);
            visible_ = false;
        }
    }

private:
    bool SwitchToSystemBackdrop(std::string& reason)
    {
        capture_mode_ = CaptureMode::SystemBackdrop;
        Show();
        if (!ApplySystemBackdrop(0.25f, reason))
        {
            Hide();
            capture_mode_ = CaptureMode::None;
            return false;
        }
        Sleep(120);
        Hide();
        return true;
    }

    bool ApplySystemBackdrop(float level, std::string& reason)
    {
        if (!hwnd_)
        {
            reason = "system backdrop window is not initialized";
            return false;
        }

        HMODULE user32 = GetModuleHandleW(L"user32.dll");
        if (!user32)
        {
            reason = "GetModuleHandle(user32.dll) failed";
            return false;
        }

        auto set_window_composition_attribute =
            reinterpret_cast<SetWindowCompositionAttributeFn>(
                GetProcAddress(user32, "SetWindowCompositionAttribute"));
        if (!set_window_composition_attribute)
        {
            reason = "SetWindowCompositionAttribute was not found";
            return false;
        }

        float clamped = std::max(0.0f, std::min(1.0f, level));
        float blur_mix = std::max(0.0f, std::min(1.0f, clamped * blur_scale_));
        float target_dim = std::max(0.0f, std::min(1.0f, max_dim_amount_ * clamped));
        float surface_opacity = std::max(blur_mix, target_dim);
        BYTE surface_alpha = static_cast<BYTE>(
            std::max(0.0f, std::min(255.0f, std::round(255.0f * surface_opacity))));
        BYTE tint_alpha = 0;
        if (surface_opacity > 0.001f)
        {
            tint_alpha = static_cast<BYTE>(
                std::max(0.0f, std::min(255.0f, std::round(255.0f * target_dim / surface_opacity))));
        }

        if (!SetLayeredWindowAttributes(hwnd_, 0, surface_alpha, LWA_ALPHA))
        {
            reason = "SetLayeredWindowAttributes failed: GetLastError " +
                std::to_string(GetLastError());
            return false;
        }

        AccentPolicy accent = {};
        accent.accent_state = blur_mix > 0.001f
            ? kAccentEnableAcrylicBlurBehind
            : kAccentEnableTransparentGradient;
        accent.accent_flags = 0;
        accent.gradient_color = static_cast<DWORD>(tint_alpha) << 24;
        accent.animation_id = 0;

        WindowCompositionAttributeData data = {};
        data.attribute = kWcaAccentPolicy;
        data.data = &accent;
        data.size_of_data = sizeof(accent);

        if (set_window_composition_attribute(hwnd_, &data))
        {
            return true;
        }

        DWORD acrylic_error = GetLastError();
        if (blur_mix > 0.001f)
        {
            accent.accent_state = kAccentEnableBlurBehind;
            if (set_window_composition_attribute(hwnd_, &data))
            {
                return true;
            }
        }

        DWORD blur_error = GetLastError();
        accent.accent_state = kAccentEnableTransparentGradient;
        if (set_window_composition_attribute(hwnd_, &data))
        {
            return true;
        }

        DWORD gradient_error = GetLastError();
        reason = "SetWindowCompositionAttribute failed: acrylic GetLastError " +
            std::to_string(acrylic_error) + ", blur GetLastError " +
            std::to_string(blur_error) + ", gradient GetLastError " +
            std::to_string(gradient_error);
        return false;
    }

    bool CreateDevice(std::string& reason)
    {
        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        D3D_FEATURE_LEVEL requested_levels[] = {
            D3D_FEATURE_LEVEL_11_1,
            D3D_FEATURE_LEVEL_11_0,
            D3D_FEATURE_LEVEL_10_1,
            D3D_FEATURE_LEVEL_10_0,
        };
        D3D_FEATURE_LEVEL actual_level = D3D_FEATURE_LEVEL_11_0;
        HRESULT hr = D3D11CreateDevice(
            adapter_.Get(),
            D3D_DRIVER_TYPE_UNKNOWN,
            nullptr,
            flags,
            requested_levels,
            ARRAYSIZE(requested_levels),
            D3D11_SDK_VERSION,
            device_.GetAddressOf(),
            &actual_level,
            context_.GetAddressOf());

        if (hr == E_INVALIDARG)
        {
            hr = D3D11CreateDevice(
                adapter_.Get(),
                D3D_DRIVER_TYPE_UNKNOWN,
                nullptr,
                flags,
                requested_levels + 1,
                ARRAYSIZE(requested_levels) - 1,
                D3D11_SDK_VERSION,
                device_.GetAddressOf(),
                &actual_level,
                context_.GetAddressOf());
        }

        if (FAILED(hr))
        {
            reason = "D3D11CreateDevice failed: " + HrToString(hr);
            return false;
        }
        return true;
    }

    bool CreateWindowAndComposition(std::string& reason)
    {
        DWORD ex_style =
            WS_EX_TOPMOST |
            WS_EX_NOACTIVATE |
            WS_EX_TRANSPARENT |
            WS_EX_TOOLWINDOW |
            WS_EX_LAYERED;

        hwnd_ = CreateWindowExW(
            ex_style,
            kWindowClassName,
            L"EchoPosture Blur Overlay",
            WS_POPUP,
            rect_.left,
            rect_.top,
            static_cast<int>(width_),
            static_cast<int>(height_),
            nullptr,
            nullptr,
            instance_,
            nullptr);
        if (!hwnd_)
        {
            reason = "CreateWindowExW failed";
            return false;
        }

        if (!SetWindowDisplayAffinity(hwnd_, kWdaExcludeFromCapture))
        {
            reason = "SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) failed";
            return false;
        }

        ComPtr<IDXGIDevice> dxgi_device;
        HRESULT hr = device_.As(&dxgi_device);
        if (FAILED(hr))
        {
            reason = "Query IDXGIDevice failed: " + HrToString(hr);
            return false;
        }

        hr = DCompositionCreateDevice(
            dxgi_device.Get(),
            __uuidof(IDCompositionDevice),
            reinterpret_cast<void**>(dcomp_device_.GetAddressOf()));
        if (FAILED(hr))
        {
            reason = "DCompositionCreateDevice failed: " + HrToString(hr);
            return false;
        }

        ComPtr<IDXGIFactory2> factory;
        hr = adapter_->GetParent(__uuidof(IDXGIFactory2), reinterpret_cast<void**>(factory.GetAddressOf()));
        if (FAILED(hr))
        {
            reason = "IDXGIAdapter::GetParent(IDXGIFactory2) failed: " + HrToString(hr);
            return false;
        }

        DXGI_SWAP_CHAIN_DESC1 desc = {};
        desc.Width = width_;
        desc.Height = height_;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.Stereo = FALSE;
        desc.SampleDesc.Count = 1;
        desc.SampleDesc.Quality = 0;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2;
        desc.Scaling = DXGI_SCALING_STRETCH;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
        desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;

        hr = factory->CreateSwapChainForComposition(
            device_.Get(),
            &desc,
            nullptr,
            swap_chain_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateSwapChainForComposition failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_device_->CreateTargetForHwnd(hwnd_, TRUE, dcomp_target_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateTargetForHwnd failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_device_->CreateVisual(dcomp_visual_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateVisual failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_visual_->SetContent(swap_chain_.Get());
        if (FAILED(hr))
        {
            reason = "IDCompositionVisual::SetContent failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_target_->SetRoot(dcomp_visual_.Get());
        if (FAILED(hr))
        {
            reason = "IDCompositionTarget::SetRoot failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_device_->Commit();
        if (FAILED(hr))
        {
            reason = "IDCompositionDevice::Commit failed: " + HrToString(hr);
            return false;
        }

        return true;
    }

    bool CreateDuplication(std::string& reason)
    {
        HRESULT hr = output_.As(&output1_);
        if (FAILED(hr))
        {
            reason = "Query IDXGIOutput1 failed: " + HrToString(hr);
            return false;
        }

        hr = output1_->DuplicateOutput(device_.Get(), duplication_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "IDXGIOutput1::DuplicateOutput failed: " + HrToString(hr);
            return false;
        }
        return true;
    }

    bool CreateGdiCaptureResources(std::string& reason)
    {
        if (memory_dc_ && dib_bits_)
        {
            return true;
        }

        HDC setup_dc = GetDC(nullptr);
        if (!setup_dc)
        {
            reason = "GetDC(NULL) failed";
            return false;
        }

        memory_dc_ = CreateCompatibleDC(setup_dc);
        if (!memory_dc_)
        {
            ReleaseDC(nullptr, setup_dc);
            reason = "CreateCompatibleDC failed";
            return false;
        }

        BITMAPINFO info = {};
        info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
        info.bmiHeader.biWidth = static_cast<LONG>(width_);
        info.bmiHeader.biHeight = -static_cast<LONG>(height_);
        info.bmiHeader.biPlanes = 1;
        info.bmiHeader.biBitCount = 32;
        info.bmiHeader.biCompression = BI_RGB;

        dib_ = CreateDIBSection(setup_dc, &info, DIB_RGB_COLORS, &dib_bits_, nullptr, 0);
        ReleaseDC(nullptr, setup_dc);
        if (!dib_ || !dib_bits_)
        {
            reason = "CreateDIBSection failed";
            return false;
        }

        previous_bitmap_ = SelectObject(memory_dc_, dib_);
        if (!previous_bitmap_)
        {
            reason = "SelectObject capture bitmap failed";
            return false;
        }
        return true;
    }

    void DestroyGdiCaptureResources()
    {
        if (memory_dc_ && previous_bitmap_)
        {
            SelectObject(memory_dc_, previous_bitmap_);
            previous_bitmap_ = nullptr;
        }
        if (dib_)
        {
            DeleteObject(dib_);
            dib_ = nullptr;
            dib_bits_ = nullptr;
        }
        if (memory_dc_)
        {
            DeleteDC(memory_dc_);
            memory_dc_ = nullptr;
        }
    }

    bool CreateShaders(std::string& reason)
    {
        ComPtr<ID3DBlob> vs_blob;
        if (!CompileShader(kVertexShader, "main", "vs_5_0", vs_blob.GetAddressOf(), reason))
        {
            return false;
        }
        HRESULT hr = device_->CreateVertexShader(
            vs_blob->GetBufferPointer(),
            vs_blob->GetBufferSize(),
            nullptr,
            vertex_shader_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateVertexShader failed: " + HrToString(hr);
            return false;
        }

        if (!CreatePixelShader(kCopyPixelShader, copy_shader_.GetAddressOf(), reason) ||
            !CreatePixelShader(kBlurHPixelShader, blur_h_shader_.GetAddressOf(), reason) ||
            !CreatePixelShader(kBlurVPixelShader, blur_v_shader_.GetAddressOf(), reason) ||
            !CreatePixelShader(kCompositePixelShader, composite_shader_.GetAddressOf(), reason))
        {
            return false;
        }

        D3D11_SAMPLER_DESC sampler_desc = {};
        sampler_desc.Filter = D3D11_FILTER_MIN_MAG_MIP_LINEAR;
        sampler_desc.AddressU = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.AddressV = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        sampler_desc.MaxLOD = D3D11_FLOAT32_MAX;
        hr = device_->CreateSamplerState(&sampler_desc, sampler_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateSamplerState failed: " + HrToString(hr);
            return false;
        }

        D3D11_BUFFER_DESC buffer_desc = {};
        buffer_desc.ByteWidth = sizeof(ShaderParams);
        buffer_desc.Usage = D3D11_USAGE_DYNAMIC;
        buffer_desc.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
        buffer_desc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        hr = device_->CreateBuffer(&buffer_desc, nullptr, constant_buffer_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateBuffer constant buffer failed: " + HrToString(hr);
            return false;
        }

        return true;
    }

    bool CreatePixelShader(const char* source, ID3D11PixelShader** shader, std::string& reason)
    {
        ComPtr<ID3DBlob> blob;
        if (!CompileShader(source, "main", "ps_5_0", blob.GetAddressOf(), reason))
        {
            return false;
        }

        HRESULT hr = device_->CreatePixelShader(
            blob->GetBufferPointer(),
            blob->GetBufferSize(),
            nullptr,
            shader);
        if (FAILED(hr))
        {
            reason = "CreatePixelShader failed: " + HrToString(hr);
            return false;
        }
        return true;
    }

    bool CreateResources(std::string& reason)
    {
        D3D11_TEXTURE2D_DESC frame_desc = {};
        frame_desc.Width = width_;
        frame_desc.Height = height_;
        frame_desc.MipLevels = 1;
        frame_desc.ArraySize = 1;
        frame_desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        frame_desc.SampleDesc.Count = 1;
        frame_desc.Usage = D3D11_USAGE_DEFAULT;
        frame_desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;

        HRESULT hr = device_->CreateTexture2D(&frame_desc, nullptr, frame_texture_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateTexture2D frame texture failed: " + HrToString(hr);
            return false;
        }

        hr = device_->CreateShaderResourceView(frame_texture_.Get(), nullptr, frame_srv_.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateShaderResourceView frame failed: " + HrToString(hr);
            return false;
        }

        if (!CreateRenderTexture(low_width_, low_height_, temp_a_.GetAddressOf(), temp_a_rtv_.GetAddressOf(), temp_a_srv_.GetAddressOf(), reason) ||
            !CreateRenderTexture(low_width_, low_height_, temp_b_.GetAddressOf(), temp_b_rtv_.GetAddressOf(), temp_b_srv_.GetAddressOf(), reason))
        {
            return false;
        }

        return true;
    }

    bool CreateRenderTexture(
        UINT width,
        UINT height,
        ID3D11Texture2D** texture,
        ID3D11RenderTargetView** rtv,
        ID3D11ShaderResourceView** srv,
        std::string& reason)
    {
        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = width;
        desc.Height = height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

        HRESULT hr = device_->CreateTexture2D(&desc, nullptr, texture);
        if (FAILED(hr))
        {
            reason = "CreateTexture2D render texture failed: " + HrToString(hr);
            return false;
        }

        hr = device_->CreateRenderTargetView(*texture, nullptr, rtv);
        if (FAILED(hr))
        {
            reason = "CreateRenderTargetView failed: " + HrToString(hr);
            return false;
        }

        hr = device_->CreateShaderResourceView(*texture, nullptr, srv);
        if (FAILED(hr))
        {
            reason = "CreateShaderResourceView render texture failed: " + HrToString(hr);
            return false;
        }

        return true;
    }

    bool AcquireFrame(UINT timeout_ms, std::string& reason)
    {
        if (capture_mode_ == CaptureMode::Gdi)
        {
            return AcquireGdiFrame(reason);
        }

        DXGI_OUTDUPL_FRAME_INFO frame_info = {};
        ComPtr<IDXGIResource> resource;
        HRESULT hr = duplication_->AcquireNextFrame(timeout_ms, &frame_info, resource.GetAddressOf());
        if (hr == DXGI_ERROR_WAIT_TIMEOUT)
        {
            std::string gdi_reason;
            if (CreateGdiCaptureResources(gdi_reason) && AcquireGdiFrame(gdi_reason))
            {
                return true;
            }
            if (!has_frame_)
            {
                reason = "desktop duplication timed out before first frame";
                if (!gdi_reason.empty())
                {
                    reason += "; GDI capture fallback failed: " + gdi_reason;
                }
                return false;
            }
            return true;
        }
        if (hr == DXGI_ERROR_ACCESS_LOST)
        {
            reason = "desktop duplication access lost";
            return false;
        }
        if (FAILED(hr))
        {
            reason = "AcquireNextFrame failed: " + HrToString(hr);
            return false;
        }

        ComPtr<ID3D11Texture2D> acquired_texture;
        hr = resource.As(&acquired_texture);
        if (SUCCEEDED(hr))
        {
            context_->CopyResource(frame_texture_.Get(), acquired_texture.Get());
            has_frame_ = true;
        }
        duplication_->ReleaseFrame();

        if (FAILED(hr))
        {
            reason = "Query acquired texture failed: " + HrToString(hr);
            return false;
        }

        return true;
    }

    bool AcquireGdiFrame(std::string& reason)
    {
        if (!memory_dc_ || !dib_bits_)
        {
            reason = "GDI capture resources are not initialized";
            return false;
        }

        if (visible_)
        {
            Hide();
            DwmFlush();
        }

        DWORD error = 0;
        HWND desktop = GetDesktopWindow();
        HDC source_dc = GetDC(nullptr);
        BOOL copied = source_dc ? BitBlt(
            memory_dc_,
            0,
            0,
            static_cast<int>(width_),
            static_cast<int>(height_),
            source_dc,
            rect_.left,
            rect_.top,
            SRCCOPY | CAPTUREBLT) : FALSE;
        if (!copied)
        {
            error = GetLastError();
        }
        if (source_dc)
        {
            ReleaseDC(nullptr, source_dc);
        }

        if (!copied)
        {
            source_dc = GetWindowDC(desktop);
            copied = source_dc ? BitBlt(
                memory_dc_,
                0,
                0,
                static_cast<int>(width_),
                static_cast<int>(height_),
                source_dc,
                rect_.left,
                rect_.top,
                SRCCOPY | CAPTUREBLT) : FALSE;
            if (!copied)
            {
                error = GetLastError();
            }
            if (source_dc)
            {
                ReleaseDC(desktop, source_dc);
            }
        }

        if (!copied)
        {
            source_dc = CreateDCW(L"DISPLAY", nullptr, nullptr, nullptr);
            copied = source_dc ? BitBlt(
                memory_dc_,
                0,
                0,
                static_cast<int>(width_),
                static_cast<int>(height_),
                source_dc,
                rect_.left,
                rect_.top,
                SRCCOPY | CAPTUREBLT) : FALSE;
            if (!copied)
            {
                error = GetLastError();
            }
            if (source_dc)
            {
                DeleteDC(source_dc);
            }
        }

        if (!copied)
        {
            reason = "BitBlt desktop capture failed: GetLastError " + std::to_string(error);
            return false;
        }

        context_->UpdateSubresource(
            frame_texture_.Get(),
            0,
            nullptr,
            dib_bits_,
            width_ * 4,
            0);
        has_frame_ = true;
        return true;
    }

    bool DetectMarkerInCapture(bool& marker_seen, std::string& reason)
    {
        marker_seen = false;

        if (capture_mode_ == CaptureMode::Gdi)
        {
            if (!AcquireGdiFrame(reason))
            {
                return false;
            }

            const unsigned char* base = static_cast<const unsigned char*>(dib_bits_);
            for (UINT y = 0; y < std::min<UINT>(16, height_); ++y)
            {
                const unsigned char* row = base + y * width_ * 4;
                for (UINT x = 0; x < std::min<UINT>(16, width_); ++x)
                {
                    const unsigned char* pixel = row + x * 4;
                    unsigned char blue = pixel[0];
                    unsigned char green = pixel[1];
                    unsigned char red = pixel[2];
                    if (red > 220 && blue > 220 && green < 80)
                    {
                        marker_seen = true;
                        break;
                    }
                }
                if (marker_seen)
                {
                    break;
                }
            }
            return true;
        }

        DXGI_OUTDUPL_FRAME_INFO frame_info = {};
        ComPtr<IDXGIResource> resource;
        HRESULT hr = duplication_->AcquireNextFrame(150, &frame_info, resource.GetAddressOf());
        if (hr == DXGI_ERROR_WAIT_TIMEOUT)
        {
            reason = "desktop duplication probe timed out";
            return false;
        }
        if (FAILED(hr))
        {
            reason = "probe AcquireNextFrame failed: " + HrToString(hr);
            return false;
        }

        ComPtr<ID3D11Texture2D> acquired_texture;
        hr = resource.As(&acquired_texture);
        if (FAILED(hr))
        {
            duplication_->ReleaseFrame();
            reason = "probe Query acquired texture failed: " + HrToString(hr);
            return false;
        }

        D3D11_TEXTURE2D_DESC desc = {};
        desc.Width = 16;
        desc.Height = 16;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.Usage = D3D11_USAGE_STAGING;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;

        ComPtr<ID3D11Texture2D> staging;
        hr = device_->CreateTexture2D(&desc, nullptr, staging.GetAddressOf());
        if (FAILED(hr))
        {
            duplication_->ReleaseFrame();
            reason = "probe staging texture failed: " + HrToString(hr);
            return false;
        }

        D3D11_BOX box = {};
        box.left = 4;
        box.top = 4;
        box.front = 0;
        box.right = 20;
        box.bottom = 20;
        box.back = 1;
        context_->CopySubresourceRegion(staging.Get(), 0, 0, 0, 0, acquired_texture.Get(), 0, &box);
        duplication_->ReleaseFrame();

        D3D11_MAPPED_SUBRESOURCE mapped = {};
        hr = context_->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped);
        if (FAILED(hr))
        {
            reason = "probe Map failed: " + HrToString(hr);
            return false;
        }

        const unsigned char* base = static_cast<const unsigned char*>(mapped.pData);
        for (UINT y = 0; y < desc.Height; ++y)
        {
            const unsigned char* row = base + y * mapped.RowPitch;
            for (UINT x = 0; x < desc.Width; ++x)
            {
                const unsigned char* pixel = row + x * 4;
                unsigned char blue = pixel[0];
                unsigned char green = pixel[1];
                unsigned char red = pixel[2];
                if (red > 220 && blue > 220 && green < 80)
                {
                    marker_seen = true;
                    break;
                }
            }
            if (marker_seen)
            {
                break;
            }
        }
        context_->Unmap(staging.Get(), 0);
        return true;
    }

    bool Render(float level, bool marker, std::string& reason)
    {
        ComPtr<ID3D11Texture2D> back_buffer;
        HRESULT hr = swap_chain_->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(back_buffer.GetAddressOf()));
        if (FAILED(hr))
        {
            reason = "SwapChain GetBuffer failed: " + HrToString(hr);
            return false;
        }

        ComPtr<ID3D11RenderTargetView> back_buffer_rtv;
        hr = device_->CreateRenderTargetView(back_buffer.Get(), nullptr, back_buffer_rtv.GetAddressOf());
        if (FAILED(hr))
        {
            reason = "CreateRenderTargetView back buffer failed: " + HrToString(hr);
            return false;
        }

        float clamped_level = std::max(0.0f, std::min(1.0f, level));
        float blur_mix = clamped_level * blur_scale_;
        float radius = 0.4f + 7.0f * blur_mix;
        float dim = max_dim_amount_ * clamped_level;

        SetCommonState();
        DrawPass(temp_a_rtv_.Get(), low_width_, low_height_, frame_srv_.Get(), copy_shader_.Get(), 1.0f / low_width_, 1.0f / low_height_, radius, blur_mix, dim, marker);
        DrawPass(temp_b_rtv_.Get(), low_width_, low_height_, temp_a_srv_.Get(), blur_h_shader_.Get(), 1.0f / low_width_, 1.0f / low_height_, radius, blur_mix, dim, marker);
        DrawPass(temp_a_rtv_.Get(), low_width_, low_height_, temp_b_srv_.Get(), blur_v_shader_.Get(), 1.0f / low_width_, 1.0f / low_height_, radius, blur_mix, dim, marker);
        DrawPass(back_buffer_rtv.Get(), width_, height_, temp_a_srv_.Get(), composite_shader_.Get(), 1.0f / width_, 1.0f / height_, radius, blur_mix, dim, marker, frame_srv_.Get());
        UnbindSrv();

        hr = swap_chain_->Present(1, 0);
        if (FAILED(hr))
        {
            reason = "SwapChain Present failed: " + HrToString(hr);
            return false;
        }

        hr = dcomp_device_->Commit();
        if (FAILED(hr))
        {
            reason = "DirectComposition Commit failed: " + HrToString(hr);
            return false;
        }

        return true;
    }

    void SetCommonState()
    {
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->IASetInputLayout(nullptr);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        ID3D11SamplerState* samplers[] = { sampler_.Get() };
        context_->PSSetSamplers(0, 1, samplers);
        ID3D11Buffer* buffers[] = { constant_buffer_.Get() };
        context_->PSSetConstantBuffers(0, 1, buffers);
    }

    void DrawPass(
        ID3D11RenderTargetView* rtv,
        UINT viewport_w,
        UINT viewport_h,
        ID3D11ShaderResourceView* srv,
        ID3D11PixelShader* shader,
        float texel_x,
        float texel_y,
        float radius,
        float level,
        float dim,
        bool marker,
        ID3D11ShaderResourceView* secondary_srv = nullptr)
    {
        UnbindSrv();
        D3D11_VIEWPORT viewport = {};
        viewport.TopLeftX = 0.0f;
        viewport.TopLeftY = 0.0f;
        viewport.Width = static_cast<float>(viewport_w);
        viewport.Height = static_cast<float>(viewport_h);
        viewport.MinDepth = 0.0f;
        viewport.MaxDepth = 1.0f;
        context_->RSSetViewports(1, &viewport);

        ID3D11RenderTargetView* rtvs[] = { rtv };
        context_->OMSetRenderTargets(1, rtvs, nullptr);

        D3D11_MAPPED_SUBRESOURCE mapped = {};
        if (SUCCEEDED(context_->Map(constant_buffer_.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped)))
        {
            ShaderParams params = {};
            params.texel_x = texel_x;
            params.texel_y = texel_y;
            params.radius = radius;
            params.level = level;
            params.dim_amount = dim;
            params.output_w = static_cast<float>(viewport_w);
            params.output_h = static_cast<float>(viewport_h);
            params.marker = marker ? 1.0f : 0.0f;
            memcpy(mapped.pData, &params, sizeof(params));
            context_->Unmap(constant_buffer_.Get(), 0);
        }

        ID3D11ShaderResourceView* srvs[] = { srv, secondary_srv };
        context_->PSSetShaderResources(0, 2, srvs);
        context_->PSSetShader(shader, nullptr, 0);
        context_->Draw(3, 0);
    }

    void UnbindSrv()
    {
        ID3D11ShaderResourceView* null_srvs[] = { nullptr, nullptr };
        context_->PSSetShaderResources(0, 2, null_srvs);
    }

    void Show()
    {
        if (!visible_)
        {
            SetWindowPos(
                hwnd_,
                HWND_TOPMOST,
                rect_.left,
                rect_.top,
                static_cast<int>(width_),
                static_cast<int>(height_),
                SWP_NOACTIVATE | SWP_SHOWWINDOW);
            visible_ = true;
        }
    }

    HINSTANCE instance_ = nullptr;
    ComPtr<IDXGIAdapter1> adapter_;
    ComPtr<IDXGIOutput> output_;
    ComPtr<IDXGIOutput1> output1_;
    DXGI_OUTPUT_DESC output_desc_ = {};
    RECT rect_ = {};
    UINT width_ = 1;
    UINT height_ = 1;
    UINT low_width_ = 1;
    UINT low_height_ = 1;
    HWND hwnd_ = nullptr;
    bool visible_ = false;
    bool has_frame_ = false;
    float max_dim_amount_ = kMaxDimAmount;
    float blur_scale_ = 1.0f;
    CaptureMode capture_mode_ = CaptureMode::None;

    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<IDXGIOutputDuplication> duplication_;
    ComPtr<IDXGISwapChain1> swap_chain_;
    ComPtr<IDCompositionDevice> dcomp_device_;
    ComPtr<IDCompositionTarget> dcomp_target_;
    ComPtr<IDCompositionVisual> dcomp_visual_;

    ComPtr<ID3D11VertexShader> vertex_shader_;
    ComPtr<ID3D11PixelShader> copy_shader_;
    ComPtr<ID3D11PixelShader> blur_h_shader_;
    ComPtr<ID3D11PixelShader> blur_v_shader_;
    ComPtr<ID3D11PixelShader> composite_shader_;
    ComPtr<ID3D11SamplerState> sampler_;
    ComPtr<ID3D11Buffer> constant_buffer_;

    ComPtr<ID3D11Texture2D> frame_texture_;
    ComPtr<ID3D11ShaderResourceView> frame_srv_;
    ComPtr<ID3D11Texture2D> temp_a_;
    ComPtr<ID3D11RenderTargetView> temp_a_rtv_;
    ComPtr<ID3D11ShaderResourceView> temp_a_srv_;
    ComPtr<ID3D11Texture2D> temp_b_;
    ComPtr<ID3D11RenderTargetView> temp_b_rtv_;
    ComPtr<ID3D11ShaderResourceView> temp_b_srv_;

    HDC memory_dc_ = nullptr;
    HBITMAP dib_ = nullptr;
    HGDIOBJ previous_bitmap_ = nullptr;
    void* dib_bits_ = nullptr;
};

class BlurOverlayHost
{
public:
    bool Initialize(HINSTANCE instance, DWORD parent_pid, bool self_test)
    {
        instance_ = instance;
        parent_pid_ = parent_pid;
        self_test_ = self_test;
        last_input_ms_.store(NowMs());

        if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        {
            SetProcessDPIAware();
        }

        if (!IsWindows10_2004OrNewer())
        {
            EnterFallback("Windows 10 2004 or newer is required for capture exclusion");
            return false;
        }

        std::string reason;
        if (!RegisterOverlayWindowClass(instance_, reason))
        {
            EnterFallback(reason);
            return false;
        }

        if (!RegisterHotKey(nullptr, kHotkeyId, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, 'E'))
        {
            // Hotkey conflicts should not disable the visual path; the parent process can still stop us.
        }

        if (parent_pid_ != 0)
        {
            parent_process_ = OpenProcess(SYNCHRONIZE, FALSE, parent_pid_);
        }

        if (!CreatePipelines(reason))
        {
            EnterFallback(reason);
            return false;
        }

        mode_ = "gpu";
        healthy_ = true;
        fallback_reason_.clear();
        PrintStatus();

        if (self_test_)
        {
            if (!RunSelfProbes(reason))
            {
                EnterFallback(reason);
                PrintStatus();
                return false;
            }
            PrintStatus();
        }

        return true;
    }

    int Run()
    {
        StartInputThread();

        auto previous = std::chrono::steady_clock::now();
        auto next_frame = previous;
        auto next_status = previous;

        while (running_.load())
        {
            MSG msg = {};
            while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE))
            {
                if (msg.message == WM_HOTKEY && msg.wParam == kHotkeyId)
                {
                    running_.store(false);
                    break;
                }
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }

            if (!running_.load())
            {
                break;
            }

            if (shutdown_requested_.exchange(false))
            {
                running_.store(false);
                break;
            }

            if (ParentGone() || HeartbeatExpired())
            {
                running_.store(false);
                break;
            }

            auto now = std::chrono::steady_clock::now();
            if (now >= next_frame)
            {
                double dt = std::chrono::duration<double>(now - previous).count();
                previous = now;
                Tick(dt);
                next_frame = now + std::chrono::milliseconds(frame_interval_ms_);
            }

            if (now >= next_status)
            {
                UpdateFps(now);
                PrintStatus();
                next_status = now + std::chrono::milliseconds(250);
            }

            DWORD wait_ms = 1;
            MsgWaitForMultipleObjects(0, nullptr, FALSE, wait_ms, QS_ALLINPUT);
        }

        target_active_.store(false);
        level_ = 0.0f;
        HideAll();
        PrintStatus("disabled", false, "host stopped");

        if (input_thread_.joinable())
        {
            if (GetStdHandle(STD_INPUT_HANDLE) != INVALID_HANDLE_VALUE)
            {
                // The input thread exits naturally when stdin closes. Detach during shutdown to avoid
                // blocking if the parent keeps the pipe open while the process is already clearing.
            }
            input_thread_.detach();
        }
        UnregisterHotKey(nullptr, kHotkeyId);
        if (parent_process_)
        {
            CloseHandle(parent_process_);
            parent_process_ = nullptr;
        }
        return 0;
    }

    int RunSelfTestOnly()
    {
        std::string reason;
        bool initialized = Initialize(GetModuleHandleW(nullptr), 0, true);
        if (!initialized || mode_ != "gpu")
        {
            PrintStatus();
            return 1;
        }
        HideAll();
        PrintStatus("disabled", true, nullptr);
        return 0;
    }

private:
    bool CreatePipelines(std::string& reason)
    {
        ComPtr<IDXGIFactory1> factory;
        HRESULT hr = CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(factory.GetAddressOf()));
        if (FAILED(hr))
        {
            reason = "CreateDXGIFactory1 failed: " + HrToString(hr);
            return false;
        }

        for (UINT adapter_index = 0;; ++adapter_index)
        {
            ComPtr<IDXGIAdapter1> adapter;
            hr = factory->EnumAdapters1(adapter_index, adapter.GetAddressOf());
            if (hr == DXGI_ERROR_NOT_FOUND)
            {
                break;
            }
            if (FAILED(hr))
            {
                continue;
            }

            DXGI_ADAPTER_DESC1 adapter_desc = {};
            adapter->GetDesc1(&adapter_desc);
            if (adapter_desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)
            {
                continue;
            }

            for (UINT output_index = 0;; ++output_index)
            {
                ComPtr<IDXGIOutput> output;
                hr = adapter->EnumOutputs(output_index, output.GetAddressOf());
                if (hr == DXGI_ERROR_NOT_FOUND)
                {
                    break;
                }
                if (FAILED(hr))
                {
                    continue;
                }

                auto pipeline = std::make_unique<OutputPipeline>();
                std::string pipeline_reason;
                if (pipeline->Initialize(instance_, adapter.Get(), output.Get(), pipeline_reason))
                {
                    pipeline->SetVisualConfig(max_dim_amount_, blur_scale_);
                    pipelines_.push_back(std::move(pipeline));
                }
                else if (reason.empty())
                {
                    reason = pipeline_reason;
                }
            }
        }

        if (pipelines_.empty())
        {
            if (reason.empty())
            {
                reason = "no duplicatable display outputs were found";
            }
            return false;
        }
        return true;
    }

    bool RunSelfProbes(std::string& reason)
    {
        for (auto& pipeline : pipelines_)
        {
            if (!pipeline->SelfCaptureProbe(reason))
            {
                HideAll();
                return false;
            }
        }
        probe_complete_ = true;
        return true;
    }

    void Tick(double dt)
    {
        if (clear_requested_.exchange(false))
        {
            target_active_.store(false);
            level_ = 0.0f;
            HideAll();
        }

        if (boost_requested_.exchange(false))
        {
            target_active_.store(true);
            level_ = 1.0f;
        }

        if (mode_ != "gpu")
        {
            return;
        }

        bool target = target_active_.load();
        if (target && !probe_complete_)
        {
            std::string reason;
            if (!RunSelfProbes(reason))
            {
                EnterFallback(reason);
                PrintStatus();
                return;
            }
        }

        if (target)
        {
            level_ = std::min(1.0f, level_ + static_cast<float>(dt / kRampUpSeconds));
        }
        else
        {
            level_ = std::max(0.0f, level_ - static_cast<float>(dt / kRampDownSeconds));
        }

        if (level_ <= 0.001f && !target)
        {
            HideAll();
            return;
        }

        std::string reason;
        for (auto& pipeline : pipelines_)
        {
            if (!pipeline->Tick(level_, reason))
            {
                EnterFallback(reason);
                PrintStatus();
                return;
            }
        }
        ++frames_since_fps_;
    }

    void EnterFallback(const std::string& reason)
    {
        HideAll();
        pipelines_.clear();
        mode_ = "dim_fallback";
        healthy_ = false;
        fallback_reason_ = reason;
        level_ = 0.0f;
        probe_complete_ = false;
    }

    void HideAll()
    {
        for (auto& pipeline : pipelines_)
        {
            pipeline->Hide();
        }
    }

    void SetVisualConfig(float max_dim_amount, float blur_scale)
    {
        max_dim_amount_ = std::max(0.0f, std::min(0.85f, max_dim_amount));
        blur_scale_ = std::max(0.0f, std::min(1.0f, blur_scale));
        for (auto& pipeline : pipelines_)
        {
            pipeline->SetVisualConfig(max_dim_amount_, blur_scale_);
        }
    }

    void StartInputThread()
    {
        input_thread_ = std::thread([this]() {
            std::string line;
            while (running_.load() && std::getline(std::cin, line))
            {
                last_input_ms_.store(NowMs());
                if (line.find("\"type\"") == std::string::npos)
                {
                    continue;
                }
                if (line.find("shutdown") != std::string::npos)
                {
                    shutdown_requested_.store(true);
                    break;
                }
                if (line.find("clear") != std::string::npos)
                {
                    clear_requested_.store(true);
                    continue;
                }
                if (line.find("boost") != std::string::npos)
                {
                    boost_requested_.store(true);
                    continue;
                }
                if (line.find("set_target") != std::string::npos)
                {
                    bool active =
                        line.find("\"active\":true") != std::string::npos ||
                        line.find("\"active\": true") != std::string::npos;
                    target_active_.store(active);
                    continue;
                }
                if (line.find("set_config") != std::string::npos)
                {
                    float max_dim = max_dim_amount_;
                    float blur = blur_scale_;
                    ExtractJsonFloat(line, "max_dim", max_dim);
                    ExtractJsonFloat(line, "blur", blur);
                    SetVisualConfig(max_dim, blur);
                }
            }
        });
    }

    bool ParentGone()
    {
        if (!parent_process_)
        {
            return false;
        }
        return WaitForSingleObject(parent_process_, 0) == WAIT_OBJECT_0;
    }

    bool HeartbeatExpired()
    {
        if (parent_pid_ == 0 || self_test_)
        {
            return false;
        }
        return NowMs() - last_input_ms_.load() > 2000;
    }

    void UpdateFps(std::chrono::steady_clock::time_point now)
    {
        if (last_fps_time_.time_since_epoch().count() == 0)
        {
            last_fps_time_ = now;
            frames_since_fps_ = 0;
            return;
        }

        double elapsed = std::chrono::duration<double>(now - last_fps_time_).count();
        if (elapsed >= 1.0)
        {
            fps_ = frames_since_fps_ / elapsed;
            frames_since_fps_ = 0;
            last_fps_time_ = now;

            if (fps_ > 0.0 && fps_ < 45.0)
            {
                slow_frames_++;
            }
            else
            {
                slow_frames_ = 0;
            }

            if (slow_frames_ >= 3)
            {
                frame_interval_ms_ = 33;
            }
        }
    }

    void PrintStatus()
    {
        PrintStatus(mode_.c_str(), healthy_, fallback_reason_.empty() ? nullptr : fallback_reason_.c_str());
    }

    void PrintStatus(const char* mode, bool healthy, const char* reason)
    {
        bool blur_available = healthy && std::strcmp(mode, "gpu") == 0 && VariableBlurAvailable();
        std::lock_guard<std::mutex> lock(output_mutex_);
        std::cout
            << "{\"type\":\"status\","
            << "\"mode\":\"" << mode << "\","
            << "\"level\":" << level_ << ","
            << "\"fps\":" << fps_ << ","
            << "\"healthy\":" << (healthy ? "true" : "false") << ","
            << "\"blur_available\":" << (blur_available ? "true" : "false") << ","
            << "\"reason\":";
        if (reason && reason[0] != '\0')
        {
            std::cout << "\"" << JsonEscape(reason) << "\"";
        }
        else
        {
            std::cout << "null";
        }
        std::cout << "}" << std::endl;
    }

    bool VariableBlurAvailable() const
    {
        if (pipelines_.empty())
        {
            return false;
        }
        for (const auto& pipeline : pipelines_)
        {
            if (!pipeline->HasVariableBlur())
            {
                return false;
            }
        }
        return true;
    }

    int64_t NowMs() const
    {
        auto now = std::chrono::steady_clock::now().time_since_epoch();
        return std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
    }

    HINSTANCE instance_ = nullptr;
    DWORD parent_pid_ = 0;
    HANDLE parent_process_ = nullptr;
    bool self_test_ = false;
    std::vector<std::unique_ptr<OutputPipeline>> pipelines_;

    std::atomic<bool> running_{ true };
    std::atomic<bool> target_active_{ false };
    std::atomic<bool> clear_requested_{ false };
    std::atomic<bool> boost_requested_{ false };
    std::atomic<bool> shutdown_requested_{ false };
    std::atomic<int64_t> last_input_ms_{ 0 };

    std::thread input_thread_;
    std::mutex output_mutex_;
    std::string mode_ = "disabled";
    bool healthy_ = false;
    std::string fallback_reason_;
    bool probe_complete_ = false;
    float level_ = 0.0f;
    float max_dim_amount_ = kMaxDimAmount;
    float blur_scale_ = 1.0f;
    double fps_ = 0.0;
    int frame_interval_ms_ = 16;
    int slow_frames_ = 0;
    int frames_since_fps_ = 0;
    std::chrono::steady_clock::time_point last_fps_time_{};
};

DWORD ParseParentPid(int argc, wchar_t** argv)
{
    for (int i = 1; i + 1 < argc; ++i)
    {
        if (wcscmp(argv[i], L"--parent-pid") == 0)
        {
            return static_cast<DWORD>(_wtoi(argv[i + 1]));
        }
    }
    return 0;
}

bool HasArg(int argc, wchar_t** argv, const wchar_t* value)
{
    for (int i = 1; i < argc; ++i)
    {
        if (wcscmp(argv[i], value) == 0)
        {
            return true;
        }
    }
    return false;
}
}

int wmain(int argc, wchar_t** argv)
{
    HINSTANCE instance = GetModuleHandleW(nullptr);
    bool self_test = HasArg(argc, argv, L"--self-test");
    DWORD parent_pid = ParseParentPid(argc, argv);

    BlurOverlayHost host;
    if (self_test)
    {
        return host.RunSelfTestOnly();
    }

    host.Initialize(instance, parent_pid, false);
    return host.Run();
}
