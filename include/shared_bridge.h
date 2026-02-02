/*
 * RashPlayer-C: Shared Memory Bridge Header
 * Copyright (c) 2026 RashPlayer Project
 * 
 * Defines shared memory structures for Python <-> C communication
 * Uses mmap for zero-copy frame transfer
 */

#ifndef SHARED_BRIDGE_H
#define SHARED_BRIDGE_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * CONSTANTS
 * ========================================================================= */

#define RASHPLAYER_SHM_NAME         "/rashplayer_shm"
#define RASHPLAYER_MAX_FRAME_WIDTH  1920
#define RASHPLAYER_MAX_FRAME_HEIGHT 1080
#define RASHPLAYER_FRAME_CHANNELS   4  /* RGBA */
#define RASHPLAYER_MAX_TEMPLATES    32
#define RASHPLAYER_MAX_TRIGGERS     64

/* Frame buffer size: 1920 * 1080 * 4 = 8,294,400 bytes */
#define RASHPLAYER_FRAME_BUFFER_SIZE \
    (RASHPLAYER_MAX_FRAME_WIDTH * RASHPLAYER_MAX_FRAME_HEIGHT * RASHPLAYER_FRAME_CHANNELS)

/* ============================================================================
 * ENUMS
 * ========================================================================= */

typedef enum {
    GAME_STATE_IDLE = 0,
    GAME_STATE_DETECTING,
    GAME_STATE_ACTION_PENDING,
    GAME_STATE_EXECUTING,
    GAME_STATE_PAUSED,
    GAME_STATE_ERROR
} GameState;

typedef enum {
    ACTION_NONE = 0,
    ACTION_TAP,
    ACTION_SWIPE,
    ACTION_LONG_PRESS,
    ACTION_DRAG,
    ACTION_WAIT
} ActionType;

typedef enum {
    TRIGGER_TEMPLATE_MATCH = 0,
    TRIGGER_COLOR_MATCH,
    TRIGGER_EDGE_DETECT,
    TRIGGER_OCR_REGION
} TriggerType;

/* ============================================================================
 * DATA STRUCTURES
 * ========================================================================= */

/* Point in screen coordinates */
typedef struct {
    int32_t x;
    int32_t y;
} Point2D;

/* Rectangle region */
typedef struct {
    int32_t x;
    int32_t y;
    int32_t width;
    int32_t height;
} Rect2D;

/* Color in RGBA format */
typedef struct {
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
} ColorRGBA;

/* HSV color for advanced matching */
typedef struct {
    uint8_t h;  /* 0-179 */
    uint8_t s;  /* 0-255 */
    uint8_t v;  /* 0-255 */
} ColorHSV;

/* Template definition for matching */
typedef struct {
    uint32_t    id;
    char        name[64];
    uint8_t*    data;           /* Template pixel data */
    int32_t     width;
    int32_t     height;
    float       threshold;      /* Match confidence threshold 0.0-1.0 */
    Rect2D      search_region;  /* Region to search in (0,0,0,0 = full frame) */
} TemplateData;

/* Visual trigger definition */
typedef struct {
    uint32_t    id;
    char        name[64];
    TriggerType type;
    union {
        uint32_t    template_id;
        ColorHSV    color_hsv;
        struct {
            ColorHSV edge_color;
            bool     horizontal;
        } edge;
    } params;
    Rect2D      region;
    bool        active;
} VisualTrigger;

/* Vision detection result */
typedef struct {
    uint32_t    trigger_id;
    bool        found;
    float       confidence;
    Point2D     location;
    Rect2D      bounding_box;
    int64_t     timestamp_ns;
} VisionResult;

/* Action command to execute */
typedef struct {
    ActionType  type;
    Point2D     start;
    Point2D     end;            /* For swipe/drag */
    int32_t     duration_ms;
    int32_t     hold_ms;        /* For long press */
    float       randomize;      /* 0.0-1.0 randomization factor */
} ActionCommand;

/* Decision rule from YAML */
typedef struct {
    char        condition[256];
    ActionType  action;
    Point2D     action_target;
    int32_t     priority;
} DecisionRule;

/* ============================================================================
 * SHARED MEMORY LAYOUT
 * ========================================================================= */

typedef struct {
    /* Header - 64 bytes aligned */
    uint32_t    magic;          /* 0x52415348 = "RASH" */
    uint32_t    version;
    uint64_t    frame_number;
    int64_t     frame_timestamp_ns;
    
    /* Synchronization */
    volatile uint32_t   frame_ready;    /* Python sets to 1 when frame is ready */
    volatile uint32_t   result_ready;   /* C sets to 1 when result is ready */
    volatile GameState  current_state;
    uint32_t    _padding1;
    
    /* Frame metadata */
    int32_t     frame_width;
    int32_t     frame_height;
    int32_t     frame_stride;
    int32_t     _padding2;
    
    /* Performance metrics */
    int64_t     vision_latency_ns;
    int64_t     brain_latency_ns;
    int64_t     total_latency_ns;
    int64_t     _padding3;
    
    /* Vision results (up to 16 concurrent detections) */
    uint32_t        num_results;
    uint32_t        _padding4;
    VisionResult    results[16];
    
    /* Action output */
    ActionCommand   pending_action;
    
    /* Frame data follows header */
    /* Offset: sizeof(SharedMemoryHeader) aligned to 4096 */
} SharedMemoryHeader;

/* Total shared memory size */
#define RASHPLAYER_SHM_SIZE \
    (sizeof(SharedMemoryHeader) + RASHPLAYER_FRAME_BUFFER_SIZE + 4096)

/* ============================================================================
 * C-CORE API FUNCTIONS
 * ========================================================================= */

/* Initialization */
int rashplayer_init(void);
void rashplayer_shutdown(void);

/* Shared memory management */
SharedMemoryHeader* rashplayer_attach_shm(const char* name);
void rashplayer_detach_shm(SharedMemoryHeader* shm);
uint8_t* rashplayer_get_frame_buffer(SharedMemoryHeader* shm);

/* Vision Engine */
int vision_init(void);
void vision_shutdown(void);
int vision_load_template(const TemplateData* tmpl);
int vision_add_trigger(const VisualTrigger* trigger);
int vision_process_frame(SharedMemoryHeader* shm);
VisionResult* vision_find_template(const uint8_t* frame, int width, int height,
                                    const TemplateData* tmpl);
int vision_find_color_region(const uint8_t* frame, int width, int height,
                              const Rect2D* region, const ColorHSV* color,
                              int tolerance, Point2D* out_center);
int vision_detect_edge(const uint8_t* frame, int width, int height,
                        const Rect2D* region, bool horizontal,
                        int* out_position);

/* Logic Brain */
int brain_init(void);
void brain_shutdown(void);
int brain_load_rules(const DecisionRule* rules, int count);
int brain_set_state(GameState state);
GameState brain_get_state(void);
int brain_process(SharedMemoryHeader* shm);
ActionCommand* brain_evaluate(const VisionResult* results, int count);

/* Utility */
int64_t rashplayer_get_time_ns(void);
void rashplayer_log(const char* fmt, ...);

#ifdef __cplusplus
}
#endif

#endif /* SHARED_BRIDGE_H */
