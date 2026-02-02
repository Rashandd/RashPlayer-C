/*
 * Flappy Bird - Game-specific C functions
 * High-performance detection routines for Flappy Bird
 */

#ifndef FLAPPY_BIRD_FUNCTIONS_H
#define FLAPPY_BIRD_FUNCTIONS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ========== Data Structures ========== */

typedef struct {
    int x, y;           // Top-left position
    int width, height;  // Size
    int center_x, center_y;
} BirdDetection;

typedef struct {
    int x, y;
    int width, height;
    int center_x, center_y;
    bool is_top;        // Top pipe (extends from top) or bottom pipe
} PipeDetection;

typedef struct {
    int gap_x, gap_y;   // Center of gap
    int pipe_x;         // X position of pipe pair
} GapInfo;

typedef struct {
    // Bird
    float bird_x, bird_y;
    bool bird_found;
    
    // Pipes
    int pipe_count;
    
    // Gap
    float gap_center_x, gap_center_y;
    bool gap_found;
} GameVariables;

/* ========== Color Detection ========== */

/**
 * Detect bird using color in HSV space
 * 
 * @param frame_data    Raw frame data (RGBA or BGR)
 * @param width         Frame width
 * @param height        Frame height
 * @param channels      Number of channels (3 or 4)
 * @param search_region Optional search region [x, y, w, h], NULL for full frame
 * @param hsv_low       Low HSV threshold [H, S, V]
 * @param hsv_high      High HSV threshold [H, S, V]
 * @param out_bird      Output bird detection
 * @return              true if bird found, false otherwise
 */
bool detect_bird_color(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const int* search_region,
    const uint8_t hsv_low[3],
    const uint8_t hsv_high[3],
    BirdDetection* out_bird
);

/**
 * Detect all pipes using color in HSV space
 * 
 * @param frame_data    Raw frame data
 * @param width         Frame width
 * @param height        Frame height
 * @param channels      Number of channels
 * @param search_region Optional search region, NULL for full frame
 * @param hsv_low       Low HSV threshold
 * @param hsv_high      High HSV threshold
 * @param out_pipes     Output array of pipe detections
 * @param max_pipes     Maximum number of pipes to detect
 * @return              Number of pipes detected
 */
int detect_pipes_color(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const int* search_region,
    const uint8_t hsv_low[3],
    const uint8_t hsv_high[3],
    PipeDetection* out_pipes,
    int max_pipes
);

/* ========== Pipe Analysis ========== */

/**
 * Find the leftmost pipe pair and calculate gap
 * 
 * @param pipes         Array of detected pipes
 * @param pipe_count    Number of pipes
 * @param out_gap       Output gap information
 * @return              true if gap found, false otherwise
 */
bool find_leftmost_gap(
    const PipeDetection* pipes,
    int pipe_count,
    GapInfo* out_gap
);

/* ========== Decision Logic ========== */

/**
 * Decide if the bird should tap
 * 
 * @param bird          Bird detection (or NULL if not found)
 * @param gap           Gap information (or NULL if not found)
 * @param threshold     Pixels below gap to trigger tap
 * @return              true if should tap
 */
bool should_tap(
    const BirdDetection* bird,
    const GapInfo* gap,
    int threshold
);

/**
 * Extract all game variables from frame
 * 
 * @param frame_data    Raw frame data
 * @param width         Frame width
 * @param height        Frame height
 * @param channels      Number of channels
 * @param config        Configuration containing color ranges and regions
 * @param out_vars      Output game variables
 */
void extract_game_variables(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const void* config,
    GameVariables* out_vars
);

/* ========== Utility Functions ========== */

/**
 * Convert RGB to HSV
 * 
 * @param r, g, b       Input RGB values (0-255)
 * @param h, s, v       Output HSV values
 */
void rgb_to_hsv(uint8_t r, uint8_t g, uint8_t b, uint8_t* h, uint8_t* s, uint8_t* v);

/**
 * Check if HSV value is within range
 */
bool hsv_in_range(uint8_t h, uint8_t s, uint8_t v,
                   const uint8_t low[3], const uint8_t high[3]);

#ifdef __cplusplus
}
#endif

#endif /* FLAPPY_BIRD_FUNCTIONS_H */
