#include <Arduino.h>
#include <Wire.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "face_frames.h"

// ============================================================
// OLED CONFIG
// ============================================================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDRESS 0x3C

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============================================================
// MPU6050 CONFIG
// ============================================================

Adafruit_MPU6050 mpu;

// ============================================================
// BUZZER CONFIG (ESP32 CORE v3 SAFE)
// ============================================================

#define BUZZER_PIN 32
#define BUZZER_RESOLUTION 8

bool buzzerActive = false;

void buzzerTone(uint16_t freq) {
  ledcWriteTone(BUZZER_PIN, freq);   // set frequency
  ledcWrite(BUZZER_PIN, 128);        // 50% duty
  buzzerActive = true;
}

void buzzerStop() {
  if (buzzerActive) {
    ledcWrite(BUZZER_PIN, 0);        // silence
    buzzerActive = false;
  }
}

// ============================================================
// SOUND SYSTEM
// ============================================================

enum SoundMode {
  SOUND_NONE,
  SOUND_DIZZY,
  SOUND_RETURN
};

struct SoundStep {
  uint16_t freq;
  uint16_t duration;
  uint16_t pause;
};

SoundStep dizzySound[] = {
  {880, 70, 20},
  {988, 70, 20},
  {784, 70, 20},
  {659, 90, 30},
  {740, 70, 20},
  {622, 120, 40},
};

SoundStep returnSound[] = {
  {523, 80, 20},
  {659, 80, 20},
  {784, 100, 20},
  {1046, 160, 40},
};

const uint8_t DIZZY_SOUND_COUNT = sizeof(dizzySound) / sizeof(dizzySound[0]);
const uint8_t RETURN_SOUND_COUNT = sizeof(returnSound) / sizeof(returnSound[0]);

SoundMode currentSound = SOUND_NONE;

uint8_t soundIndex = 0;
uint32_t lastSoundMs = 0;
bool soundPlayingTone = false;
bool soundInPause = false;

// ============================================================
// ANIMATION SETTINGS
// ============================================================

const uint16_t BLINK_FRAME_MS = 80;
const uint16_t DIZZY_FRAME_MS = 70;
const uint32_t DIZZY_DURATION_MS = 2000;

// ============================================================
// SHAKE DETECTION SETTINGS
// ============================================================

const uint16_t MPU_SAMPLE_MS = 20;
const float SHAKE_DELTA_THRESHOLD = 4.0;
const uint32_t SHAKE_STOP_MS = 100;

// ============================================================
// FACE STATE
// ============================================================

enum FaceMode {
  FACE_BLINK,
  FACE_DIZZY
};

FaceMode currentMode = FACE_BLINK;

uint16_t currentFrame = 0;
uint32_t lastFrameMs = 0;

uint32_t dizzyStartMs = 0;
uint32_t lastMpuSampleMs = 0;

bool havePreviousAccel = false;
float previousAx = 0, previousAy = 0, previousAz = 0;

bool shakeActive = false;
uint32_t lastShakeMs = 0;

// ============================================================
// BUZZER LOGIC
// ============================================================

void startDizzySound() {
  currentSound = SOUND_DIZZY;
  soundIndex = 0;
  lastSoundMs = 0;
  soundPlayingTone = false;
  soundInPause = false;
}

void startReturnSound() {
  currentSound = SOUND_RETURN;
  soundIndex = 0;
  lastSoundMs = 0;
  soundPlayingTone = false;
  soundInPause = false;
}

void stopSound() {
  currentSound = SOUND_NONE;
  soundIndex = 0;
  soundPlayingTone = false;
  soundInPause = false;
  buzzerStop();
}

void updateBuzzer() {
  if (currentSound == SOUND_NONE) return;

  uint32_t now = millis();

  SoundStep *soundArray;
  uint8_t soundCount;
  bool shouldLoop;

  if (currentSound == SOUND_DIZZY) {
    soundArray = dizzySound;
    soundCount = DIZZY_SOUND_COUNT;
    shouldLoop = true;
  } else {
    soundArray = returnSound;
    soundCount = RETURN_SOUND_COUNT;
    shouldLoop = false;
  }

  SoundStep step = soundArray[soundIndex];

  if (!soundPlayingTone && !soundInPause) {
    buzzerTone(step.freq);
    lastSoundMs = now;
    soundPlayingTone = true;
    return;
  }

  if (soundPlayingTone && now - lastSoundMs >= step.duration) {
    buzzerStop();
    lastSoundMs = now;
    soundPlayingTone = false;
    soundInPause = true;
    return;
  }

  if (soundInPause && now - lastSoundMs >= step.pause) {
    soundInPause = false;
    soundIndex++;

    if (soundIndex >= soundCount) {
      if (shouldLoop) soundIndex = 0;
      else stopSound();
    }
  }
}

// ============================================================
// DISPLAY
// ============================================================

void drawAnimationFrame(const uint8_t frames[][FACE_FRAME_BYTES], uint16_t index) {
  display.clearDisplay();
  display.drawBitmap(0, 0, frames[index], FACE_WIDTH, FACE_HEIGHT, SSD1306_WHITE);
  display.display();
}

// ============================================================
// FACE CONTROL
// ============================================================

void setFaceMode(FaceMode newMode) {
  if (currentMode == newMode) return;

  currentMode = newMode;
  currentFrame = 0;
  lastFrameMs = 0;

  if (newMode == FACE_DIZZY) {
    dizzyStartMs = millis();
    startDizzySound();
  }

  if (newMode == FACE_BLINK) {
    startReturnSound();
  }
}

// ============================================================
// ANIMATION
// ============================================================

void updateAnimation() {
  uint32_t now = millis();

  const uint8_t (*frames)[FACE_FRAME_BYTES];
  uint16_t frameCount;
  uint16_t delayMs;

  if (currentMode == FACE_DIZZY) {
    frames = dizzyFrames;
    frameCount = DIZZY_FRAME_COUNT;
    delayMs = DIZZY_FRAME_MS;
  } else {
    frames = blinkFrames;
    frameCount = BLINK_FRAME_COUNT;
    delayMs = BLINK_FRAME_MS;
  }

  if (now - lastFrameMs >= delayMs) {
    lastFrameMs = now;
    drawAnimationFrame(frames, currentFrame);
    currentFrame = (currentFrame + 1) % frameCount;
  }

  if (currentMode == FACE_DIZZY && now - dizzyStartMs >= DIZZY_DURATION_MS) {
    setFaceMode(FACE_BLINK);
  }
}

// ============================================================
// SHAKE DETECTION
// ============================================================

void updateShakeDetection() {
  uint32_t now = millis();
  if (currentMode == FACE_DIZZY) return;
  if (now - lastMpuSampleMs < MPU_SAMPLE_MS) return;

  lastMpuSampleMs = now;

  sensors_event_t accel, gyro, temp;
  mpu.getEvent(&accel, &gyro, &temp);

  float ax = accel.acceleration.x;
  float ay = accel.acceleration.y;
  float az = accel.acceleration.z;

  if (!havePreviousAccel) {
    previousAx = ax;
    previousAy = ay;
    previousAz = az;
    havePreviousAccel = true;
    return;
  }

  float dx = ax - previousAx;
  float dy = ay - previousAy;
  float dz = az - previousAz;

  previousAx = ax;
  previousAy = ay;
  previousAz = az;

  float motionDelta = sqrt(dx * dx + dy * dy + dz * dz);

  if (motionDelta > SHAKE_DELTA_THRESHOLD) {
    shakeActive = true;
    lastShakeMs = now;
  }

  if (shakeActive && now - lastShakeMs >= SHAKE_STOP_MS) {
    shakeActive = false;
    setFaceMode(FACE_DIZZY);
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // Attach buzzer ONCE
  ledcAttach(BUZZER_PIN, 1000, BUZZER_RESOLUTION);
  ledcWrite(BUZZER_PIN, 0);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    while (true);
  }

  if (!mpu.begin()) {
    while (true);
  }

  drawAnimationFrame(blinkFrames, 0);
}

// ============================================================
// LOOP
// ============================================================

void loop() {
  updateShakeDetection();
  updateAnimation();
  updateBuzzer();
}