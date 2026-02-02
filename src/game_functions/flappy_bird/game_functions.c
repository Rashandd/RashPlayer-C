/*
 * Flappy Bird - Game-specific C functions implementation
 * High-performance detection routines using SIMD where available
 */

#include "game_functions.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* ========== Utility Functions ========== */

void rgb_to_hsv(uint8_t r, uint8_t g, uint8_t b, uint8_t* h, uint8_t* s, uint8_t* v) {
    float rf = r / 255.0f;
    float gf = g / 255.0f;
    float bf = b / 255.0f;
    
    float cmax = fmaxf(fmaxf(rf, gf), bf);
    float cmin = fminf(fminf(rf, gf), bf);
    float delta = cmax - cmin;
    
    // Hue
    float hf = 0;
    if (delta != 0) {
        if (cmax == rf) {
            hf = 60.0f * fmodf((gf - bf) / delta, 6.0f);
        } else if (cmax == gf) {
            hf = 60.0f * ((bf - rf) / delta + 2.0f);
        } else {
            hf = 60.0f * ((rf - gf) / delta + 4.0f);
        }
    }
    if (hf < 0) hf += 360.0f;
    
    // Saturation
    float sf = (cmax == 0) ? 0 : (delta / cmax);
    
    // Value
    float vf = cmax;
    
    // Convert to OpenCV scale (H: 0-180, S: 0-255, V: 0-255)
    *h = (uint8_t)(hf / 2.0f);
    *s = (uint8_t)(sf * 255.0f);
    *v = (uint8_t)(vf * 255.0f);
}

bool hsv_in_range(uint8_t h, uint8_t s, uint8_t v,
                   const uint8_t low[3], const uint8_t high[3]) {
    return h >= low[0] && h <= high[0] &&
           s >= low[1] && s <= high[1] &&
           v >= low[2] && v <= high[2];
}

/* ========== Color Detection ========== */

// Internal structure for blob tracking
typedef struct {
    int min_x, min_y;
    int max_x, max_y;
    int pixel_count;
} BlobBounds;

bool detect_bird_color(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const int* search_region,
    const uint8_t hsv_low[3],
    const uint8_t hsv_high[3],
    BirdDetection* out_bird
) {
    // Determine search bounds
    int sx = search_region ? search_region[0] : 0;
    int sy = search_region ? search_region[1] : 0;
    int sw = search_region ? search_region[2] : width;
    int sh = search_region ? search_region[3] : height;
    
    // Clamp to frame bounds
    if (sx + sw > width) sw = width - sx;
    if (sy + sh > height) sh = height - sy;
    
    BlobBounds best = {0, 0, 0, 0, 0};
    
    // Scan for matching pixels
    for (int y = sy; y < sy + sh; y++) {
        for (int x = sx; x < sx + sw; x++) {
            int idx = (y * width + x) * channels;
            
            // Get RGB (handle both RGB and RGBA)
            uint8_t r, g, b;
            if (channels == 4) {
                // RGBA format
                r = frame_data[idx];
                g = frame_data[idx + 1];
                b = frame_data[idx + 2];
            } else {
                // BGR format (OpenCV default)
                b = frame_data[idx];
                g = frame_data[idx + 1];
                r = frame_data[idx + 2];
            }
            
            // Convert to HSV and check
            uint8_t h, s, v;
            rgb_to_hsv(r, g, b, &h, &s, &v);
            
            if (hsv_in_range(h, s, v, hsv_low, hsv_high)) {
                // Update bounds of largest blob
                // Simplified: just track overall bounding box
                if (best.pixel_count == 0) {
                    best.min_x = best.max_x = x;
                    best.min_y = best.max_y = y;
                } else {
                    if (x < best.min_x) best.min_x = x;
                    if (x > best.max_x) best.max_x = x;
                    if (y < best.min_y) best.min_y = y;
                    if (y > best.max_y) best.max_y = y;
                }
                best.pixel_count++;
            }
        }
    }
    
    // Check if we found enough pixels
    if (best.pixel_count > 200) {
        out_bird->x = best.min_x;
        out_bird->y = best.min_y;
        out_bird->width = best.max_x - best.min_x + 1;
        out_bird->height = best.max_y - best.min_y + 1;
        out_bird->center_x = best.min_x + out_bird->width / 2;
        out_bird->center_y = best.min_y + out_bird->height / 2;
        return true;
    }
    
    return false;
}

int detect_pipes_color(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const int* search_region,
    const uint8_t hsv_low[3],
    const uint8_t hsv_high[3],
    PipeDetection* out_pipes,
    int max_pipes
) {
    // Determine search bounds
    int sx = search_region ? search_region[0] : 0;
    int sy = search_region ? search_region[1] : 0;
    int sw = search_region ? search_region[2] : width;
    int sh = search_region ? search_region[3] : height;
    
    // Use column-based detection for pipes (vertical objects)
    // Track columns with high green pixel density
    
    #define MAX_COLUMNS 100
    int column_counts[MAX_COLUMNS] = {0};
    int column_min_y[MAX_COLUMNS];
    int column_max_y[MAX_COLUMNS];
    
    // Initialize
    for (int i = 0; i < MAX_COLUMNS; i++) {
        column_min_y[i] = height;
        column_max_y[i] = 0;
    }
    
    int col_width = sw / MAX_COLUMNS;
    if (col_width < 1) col_width = 1;
    
    // Scan and count per column
    for (int y = sy; y < sy + sh; y++) {
        for (int x = sx; x < sx + sw; x++) {
            int idx = (y * width + x) * channels;
            
            uint8_t r, g, b;
            if (channels == 4) {
                r = frame_data[idx];
                g = frame_data[idx + 1];
                b = frame_data[idx + 2];
            } else {
                b = frame_data[idx];
                g = frame_data[idx + 1];
                r = frame_data[idx + 2];
            }
            
            uint8_t h, s, v;
            rgb_to_hsv(r, g, b, &h, &s, &v);
            
            if (hsv_in_range(h, s, v, hsv_low, hsv_high)) {
                int col = (x - sx) / col_width;
                if (col >= MAX_COLUMNS) col = MAX_COLUMNS - 1;
                
                column_counts[col]++;
                if (y < column_min_y[col]) column_min_y[col] = y;
                if (y > column_max_y[col]) column_max_y[col] = y;
            }
        }
    }
    
    // Find pipe segments (groups of high-density columns)
    int pipe_count = 0;
    int in_pipe = 0;
    int pipe_start_col = 0;
    
    for (int col = 0; col < MAX_COLUMNS && pipe_count < max_pipes; col++) {
        bool is_pipe_col = column_counts[col] > (sh / 4);  // At least 25% height
        
        if (is_pipe_col && !in_pipe) {
            // Start of pipe
            in_pipe = 1;
            pipe_start_col = col;
        } else if (!is_pipe_col && in_pipe) {
            // End of pipe
            in_pipe = 0;
            
            // Calculate pipe bounds
            int px = sx + pipe_start_col * col_width;
            int pw = (col - pipe_start_col) * col_width;
            
            // Find vertical bounds
            int py = height, ph_max = 0;
            for (int c = pipe_start_col; c < col; c++) {
                if (column_min_y[c] < py) py = column_min_y[c];
                if (column_max_y[c] > ph_max) ph_max = column_max_y[c];
            }
            int ph = ph_max - py + 1;
            
            if (pw > 20 && ph > 50) {  // Minimum pipe size
                out_pipes[pipe_count].x = px;
                out_pipes[pipe_count].y = py;
                out_pipes[pipe_count].width = pw;
                out_pipes[pipe_count].height = ph;
                out_pipes[pipe_count].center_x = px + pw / 2;
                out_pipes[pipe_count].center_y = py + ph / 2;
                out_pipes[pipe_count].is_top = (py < sh / 3);
                pipe_count++;
            }
        }
    }
    
    return pipe_count;
}

/* ========== Pipe Analysis ========== */

bool find_leftmost_gap(
    const PipeDetection* pipes,
    int pipe_count,
    GapInfo* out_gap
) {
    if (pipe_count < 2) return false;
    
    // Find leftmost pipe pair
    int best_x = 999999;
    bool found = false;
    
    for (int i = 0; i < pipe_count; i++) {
        for (int j = i + 1; j < pipe_count; j++) {
            // Check if they form a pair (close x, different types)
            int dx = abs(pipes[i].center_x - pipes[j].center_x);
            
            if (dx < 100 && pipes[i].is_top != pipes[j].is_top) {
                int pair_x = (pipes[i].center_x + pipes[j].center_x) / 2;
                
                if (pair_x < best_x) {
                    best_x = pair_x;
                    
                    // Calculate gap
                    const PipeDetection* top = pipes[i].is_top ? &pipes[i] : &pipes[j];
                    const PipeDetection* bottom = pipes[i].is_top ? &pipes[j] : &pipes[i];
                    
                    out_gap->pipe_x = pair_x;
                    out_gap->gap_x = pair_x;
                    out_gap->gap_y = (top->y + top->height + bottom->y) / 2;
                    found = true;
                }
            }
        }
    }
    
    return found;
}

/* ========== Decision Logic ========== */

bool should_tap(
    const BirdDetection* bird,
    const GapInfo* gap,
    int threshold
) {
    if (!bird || !gap) return false;
    
    // If bird is below gap center + threshold, tap
    return bird->center_y > gap->gap_y + threshold;
}

void extract_game_variables(
    const uint8_t* frame_data,
    int width, int height, int channels,
    const void* config,
    GameVariables* out_vars
) {
    // Default color ranges (can be overridden by config)
    uint8_t bird_low[3] = {20, 150, 150};
    uint8_t bird_high[3] = {40, 255, 255};
    uint8_t pipe_low[3] = {35, 100, 100};
    uint8_t pipe_high[3] = {85, 255, 255};
    
    // Detect bird
    BirdDetection bird;
    if (detect_bird_color(frame_data, width, height, channels,
                          NULL, bird_low, bird_high, &bird)) {
        out_vars->bird_x = bird.center_x;
        out_vars->bird_y = bird.center_y;
        out_vars->bird_found = true;
    } else {
        out_vars->bird_found = false;
    }
    
    // Detect pipes
    PipeDetection pipes[10];
    out_vars->pipe_count = detect_pipes_color(
        frame_data, width, height, channels,
        NULL, pipe_low, pipe_high, pipes, 10
    );
    
    // Find gap
    GapInfo gap;
    if (find_leftmost_gap(pipes, out_vars->pipe_count, &gap)) {
        out_vars->gap_center_x = gap.gap_x;
        out_vars->gap_center_y = gap.gap_y;
        out_vars->gap_found = true;
    } else {
        out_vars->gap_found = false;
    }
}
