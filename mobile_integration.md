# Mobile Application Integration Guide

This guide explains how to stream real-time camera frames from a mobile app (iOS/Android) to the FastAPI server so they appear in the **Qt desktop window**.

## Connection Details

- **Protocol:** WebSocket (`ws://`)
- **Endpoint URL:** `ws://172.20.25.16:8000/ws/stream`

> Make sure your **mobile device and the server machine are on the same Wi-Fi network**.

## Payload Format

The server expects **raw JPEG-encoded bytes sent as a binary WebSocket message** (not Base64 strings).

## Steps for Mobile Clients

1. **Establish a WebSocket Connection**  
   Open a persistent connection to `ws://172.20.25.16:8000/ws/stream`.

2. **Capture Camera Frames**  
   Use the mobile device's camera API (e.g., CameraX for Android, AVFoundation for iOS) to capture video frames continuously at the target FPS.

3. **Resize and Compress**  
   - Resize frames to 640x480 or 480x360 to minimize latency.
   - Compress to JPEG with quality between 50–80.

4. **Send as Raw Binary**  
   Convert the JPEG image to a `byte[]` and send it as a **binary WebSocket message**. Do **not** base64-encode it.

5. **Manage Connection State**  
   Reconnect automatically if the connection drops.

---

### Example (Swift/iOS)

```swift
func sendFrame(image: UIImage) {
    let resized = resizeImage(image, to: CGSize(width: 640, height: 480))
    guard let jpegData = resized.jpegData(compressionQuality: 0.6) else { return }
    let message = URLSessionWebSocketTask.Message.data(jpegData)
    webSocketTask.send(message) { error in
        if let error = error { print("WebSocket send error: \(error)") }
    }
}
```

### Example (Kotlin/Android)

```kotlin
fun sendFrame(bitmap: Bitmap) {
    val scaled = Bitmap.createScaledBitmap(bitmap, 640, 480, true)
    val stream = ByteArrayOutputStream()
    scaled.compress(Bitmap.CompressFormat.JPEG, 60, stream)
    val byteString = ByteString.of(*stream.toByteArray())
    webSocket.send(byteString)
}
```
