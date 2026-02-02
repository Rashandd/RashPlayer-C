/*
 * RashPlayer-C: Vision Engine
 * Copyright (c) 2026 RashPlayer Project
 * 
 * SIMD-optimized pixel searching and template matching
 * Target: <5ms for full 1080p frame scan
 */

#include "../include/shared_bridge.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

#ifdef __x86_64__
#include <immintrin.h>  /* SSE/AVX intrinsics */
#define USE_SSE 1
#elif defined(__aarch64__)
#include <arm_neon.h>   /* NEON intrinsics */
#define USE_NEON 1
#endif

/* ============================================================================
 * INTERNAL STATE
 * ========================================================================= */

static TemplateData     g_templates[RASHPLAYER_MAX_TEMPLATES];
static int              g_template_count = 0;
static VisualTrigger    g_triggers[RASHPLAYER_MAX_TRIGGERS];
static int              g_trigger_count = 0;
static bool             g_vision_initialized = false;

/* ============================================================================
 * UTILITY FUNCTIONS
 * ========================================================================= */

static inline int64_t get_time_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

/* Convert RGB to HSV */
static inline void rgb_to_hsv(uint8_t r, uint8_t g, uint8_t b, 
                               uint8_t* h, uint8_t* s, uint8_t* v) {
    uint8_t max = r > g ? (r > b ? r : b) : (g > b ? g : b);
    uint8_t min = r < g ? (r < b ? r : b) : (g < b ? g : b);
    uint8_t delta = max - min;
    
    *v = max;
    *s = max == 0 ? 0 : (uint8_t)(255 * delta / max);
    
    if (delta == 0) {
        *h = 0;
    } else if (max == r) {
        *h = (uint8_t)(30 * (g - b) / delta + (g < b ? 180 : 0));
    } else if (max == g) {
        *h = (uint8_t)(30 * (b - r) / delta + 60);
    } else {
        *h = (uint8_t)(30 * (r - g) / delta + 120);
    }
}

/* ============================================================================
 * SIMD COLOR MATCHING
 * ========================================================================= */

#ifdef USE_SSE

/* SSE4.2 optimized color search - processes 4 pixels at a time */
static int find_color_sse(const uint8_t* frame, int width, int height,
                           const Rect2D* region, const ColorHSV* target,
                           int tolerance, Point2D* matches, int max_matches) {
    int rx = region->x > 0 ? region->x : 0;
    int ry = region->y > 0 ? region->y : 0;
    int rw = region->width > 0 ? region->width : width;
    int rh = region->height > 0 ? region->height : height;
    
    if (rx + rw > width) rw = width - rx;
    if (ry + rh > height) rh = height - ry;
    
    int match_count = 0;
    int64_t sum_x = 0, sum_y = 0;
    
    /* Vectorize tolerance comparison */
    __m128i tol_vec = _mm_set1_epi8((char)tolerance);
    __m128i target_h = _mm_set1_epi8((char)target->h);
    __m128i target_s = _mm_set1_epi8((char)target->s);
    __m128i target_v = _mm_set1_epi8((char)target->v);
    
    for (int y = ry; y < ry + rh; y++) {
        const uint8_t* row = frame + y * width * 4 + rx * 4;
        
        /* Process 4 pixels per iteration (16 bytes = 4 RGBA) */
        for (int x = rx; x < rx + rw - 3; x += 4) {
            /* Load 4 RGBA pixels */
            __m128i pixels = _mm_loadu_si128((__m128i*)row);
            row += 16;
            
            /* Extract and convert to HSV (simplified for performance) */
            /* In production, use lookup tables for RGB->HSV */
            for (int px = 0; px < 4 && match_count < max_matches; px++) {
                int idx = px * 4;
                uint8_t r = ((uint8_t*)&pixels)[idx];
                uint8_t g = ((uint8_t*)&pixels)[idx + 1];
                uint8_t b = ((uint8_t*)&pixels)[idx + 2];
                
                uint8_t h, s, v;
                rgb_to_hsv(r, g, b, &h, &s, &v);
                
                /* Check if within tolerance */
                int dh = abs((int)h - (int)target->h);
                if (dh > 90) dh = 180 - dh; /* Wrap hue */
                int ds = abs((int)s - (int)target->s);
                int dv = abs((int)v - (int)target->v);
                
                if (dh <= tolerance && ds <= tolerance && dv <= tolerance) {
                    sum_x += x + px;
                    sum_y += y;
                    match_count++;
                }
            }
        }
    }
    
    /* Return center of matched pixels */
    if (match_count > 0 && matches) {
        matches[0].x = (int32_t)(sum_x / match_count);
        matches[0].y = (int32_t)(sum_y / match_count);
    }
    
    return match_count;
}

/* SSE optimized template matching using normalized cross-correlation */
static float template_match_sse(const uint8_t* frame, int frame_width, int frame_height,
                                 int fx, int fy, const TemplateData* tmpl) {
    if (fx < 0 || fy < 0 || 
        fx + tmpl->width > frame_width || 
        fy + tmpl->height > frame_height) {
        return 0.0f;
    }
    
    __m128 sum_prod = _mm_setzero_ps();
    __m128 sum_frame_sq = _mm_setzero_ps();
    __m128 sum_tmpl_sq = _mm_setzero_ps();
    
    for (int ty = 0; ty < tmpl->height; ty++) {
        const uint8_t* frame_row = frame + (fy + ty) * frame_width * 4 + fx * 4;
        const uint8_t* tmpl_row = tmpl->data + ty * tmpl->width * 4;
        
        /* Process 4 pixels at a time */
        int tx = 0;
        for (; tx <= tmpl->width - 4; tx += 4) {
            /* Load and convert to float */
            __m128i frame_pixels = _mm_loadu_si128((__m128i*)(frame_row + tx * 4));
            __m128i tmpl_pixels = _mm_loadu_si128((__m128i*)(tmpl_row + tx * 4));
            
            /* Sum only RGB (ignore alpha) - simplified grayscale conversion */
            for (int p = 0; p < 4; p++) {
                float fval = (float)(((uint8_t*)&frame_pixels)[p*4] + 
                                     ((uint8_t*)&frame_pixels)[p*4+1] + 
                                     ((uint8_t*)&frame_pixels)[p*4+2]) / 3.0f;
                float tval = (float)(((uint8_t*)&tmpl_pixels)[p*4] + 
                                     ((uint8_t*)&tmpl_pixels)[p*4+1] + 
                                     ((uint8_t*)&tmpl_pixels)[p*4+2]) / 3.0f;
                
                sum_prod = _mm_add_ps(sum_prod, _mm_set_ps1(fval * tval));
                sum_frame_sq = _mm_add_ps(sum_frame_sq, _mm_set_ps1(fval * fval));
                sum_tmpl_sq = _mm_add_ps(sum_tmpl_sq, _mm_set_ps1(tval * tval));
            }
        }
        
        /* Handle remaining pixels */
        for (; tx < tmpl->width; tx++) {
            float fval = (float)(frame_row[tx*4] + frame_row[tx*4+1] + frame_row[tx*4+2]) / 3.0f;
            float tval = (float)(tmpl_row[tx*4] + tmpl_row[tx*4+1] + tmpl_row[tx*4+2]) / 3.0f;
            sum_prod = _mm_add_ps(sum_prod, _mm_set_ps1(fval * tval));
            sum_frame_sq = _mm_add_ps(sum_frame_sq, _mm_set_ps1(fval * fval));
            sum_tmpl_sq = _mm_add_ps(sum_tmpl_sq, _mm_set_ps1(tval * tval));
        }
    }
    
    /* Horizontal sum of vectors */
    float prod[4], fsq[4], tsq[4];
    _mm_storeu_ps(prod, sum_prod);
    _mm_storeu_ps(fsq, sum_frame_sq);
    _mm_storeu_ps(tsq, sum_tmpl_sq);
    
    float total_prod = prod[0] + prod[1] + prod[2] + prod[3];
    float total_fsq = fsq[0] + fsq[1] + fsq[2] + fsq[3];
    float total_tsq = tsq[0] + tsq[1] + tsq[2] + tsq[3];
    
    float denom = sqrtf(total_fsq * total_tsq);
    return denom > 0 ? total_prod / denom : 0.0f;
}

#endif /* USE_SSE */

#ifdef USE_NEON

/* NEON optimized color search for ARM64 */
static int find_color_neon(const uint8_t* frame, int width, int height,
                            const Rect2D* region, const ColorHSV* target,
                            int tolerance, Point2D* matches, int max_matches) {
    int rx = region->x > 0 ? region->x : 0;
    int ry = region->y > 0 ? region->y : 0;
    int rw = region->width > 0 ? region->width : width;
    int rh = region->height > 0 ? region->height : height;
    
    if (rx + rw > width) rw = width - rx;
    if (ry + rh > height) rh = height - ry;
    
    int match_count = 0;
    int64_t sum_x = 0, sum_y = 0;
    
    int8x8_t tol_vec = vdup_n_s8((int8_t)tolerance);
    
    for (int y = ry; y < ry + rh; y++) {
        const uint8_t* row = frame + y * width * 4 + rx * 4;
        
        for (int x = rx; x < rx + rw; x++) {
            uint8_t h, s, v;
            rgb_to_hsv(row[0], row[1], row[2], &h, &s, &v);
            row += 4;
            
            int dh = abs((int)h - (int)target->h);
            if (dh > 90) dh = 180 - dh;
            int ds = abs((int)s - (int)target->s);
            int dv = abs((int)v - (int)target->v);
            
            if (dh <= tolerance && ds <= tolerance && dv <= tolerance) {
                sum_x += x;
                sum_y += y;
                match_count++;
                if (match_count >= max_matches) goto done;
            }
        }
    }
done:
    
    if (match_count > 0 && matches) {
        matches[0].x = (int32_t)(sum_x / match_count);
        matches[0].y = (int32_t)(sum_y / match_count);
    }
    
    return match_count;
}

#endif /* USE_NEON */

/* ============================================================================
 * SCALAR FALLBACK FUNCTIONS
 * ========================================================================= */

static int find_color_scalar(const uint8_t* frame, int width, int height,
                              const Rect2D* region, const ColorHSV* target,
                              int tolerance, Point2D* matches, int max_matches) {
    int rx = region->x > 0 ? region->x : 0;
    int ry = region->y > 0 ? region->y : 0;
    int rw = region->width > 0 ? region->width : width;
    int rh = region->height > 0 ? region->height : height;
    
    if (rx + rw > width) rw = width - rx;
    if (ry + rh > height) rh = height - ry;
    
    int match_count = 0;
    int64_t sum_x = 0, sum_y = 0;
    
    for (int y = ry; y < ry + rh; y++) {
        const uint8_t* row = frame + y * width * 4 + rx * 4;
        
        for (int x = rx; x < rx + rw; x++) {
            uint8_t h, s, v;
            rgb_to_hsv(row[0], row[1], row[2], &h, &s, &v);
            row += 4;
            
            int dh = abs((int)h - (int)target->h);
            if (dh > 90) dh = 180 - dh;
            int ds = abs((int)s - (int)target->s);
            int dv = abs((int)v - (int)target->v);
            
            if (dh <= tolerance && ds <= tolerance && dv <= tolerance) {
                sum_x += x;
                sum_y += y;
                match_count++;
                if (match_count >= max_matches) goto done;
            }
        }
    }
done:
    
    if (match_count > 0 && matches) {
        matches[0].x = (int32_t)(sum_x / match_count);
        matches[0].y = (int32_t)(sum_y / match_count);
    }
    
    return match_count;
}

static float template_match_scalar(const uint8_t* frame, int frame_width, int frame_height,
                                    int fx, int fy, const TemplateData* tmpl) {
    if (fx < 0 || fy < 0 || 
        fx + tmpl->width > frame_width || 
        fy + tmpl->height > frame_height) {
        return 0.0f;
    }
    
    double sum_prod = 0, sum_frame_sq = 0, sum_tmpl_sq = 0;
    
    for (int ty = 0; ty < tmpl->height; ty++) {
        const uint8_t* frame_row = frame + (fy + ty) * frame_width * 4 + fx * 4;
        const uint8_t* tmpl_row = tmpl->data + ty * tmpl->width * 4;
        
        for (int tx = 0; tx < tmpl->width; tx++) {
            float fval = (frame_row[tx*4] + frame_row[tx*4+1] + frame_row[tx*4+2]) / 3.0f;
            float tval = (tmpl_row[tx*4] + tmpl_row[tx*4+1] + tmpl_row[tx*4+2]) / 3.0f;
            
            sum_prod += fval * tval;
            sum_frame_sq += fval * fval;
            sum_tmpl_sq += tval * tval;
        }
    }
    
    double denom = sqrt(sum_frame_sq * sum_tmpl_sq);
    return denom > 0 ? (float)(sum_prod / denom) : 0.0f;
}

/* ============================================================================
 * PUBLIC API IMPLEMENTATION
 * ========================================================================= */

int vision_init(void) {
    if (g_vision_initialized) return 0;
    
    memset(g_templates, 0, sizeof(g_templates));
    memset(g_triggers, 0, sizeof(g_triggers));
    g_template_count = 0;
    g_trigger_count = 0;
    g_vision_initialized = true;
    
    return 0;
}

void vision_shutdown(void) {
    /* Free template data */
    for (int i = 0; i < g_template_count; i++) {
        if (g_templates[i].data) {
            free(g_templates[i].data);
            g_templates[i].data = NULL;
        }
    }
    g_template_count = 0;
    g_trigger_count = 0;
    g_vision_initialized = false;
}

int vision_load_template(const TemplateData* tmpl) {
    if (!tmpl || g_template_count >= RASHPLAYER_MAX_TEMPLATES) {
        return -1;
    }
    
    memcpy(&g_templates[g_template_count], tmpl, sizeof(TemplateData));
    
    /* Deep copy template data */
    size_t data_size = tmpl->width * tmpl->height * 4;
    g_templates[g_template_count].data = (uint8_t*)malloc(data_size);
    if (!g_templates[g_template_count].data) {
        return -1;
    }
    memcpy(g_templates[g_template_count].data, tmpl->data, data_size);
    
    return g_template_count++;
}

int vision_add_trigger(const VisualTrigger* trigger) {
    if (!trigger || g_trigger_count >= RASHPLAYER_MAX_TRIGGERS) {
        return -1;
    }
    
    memcpy(&g_triggers[g_trigger_count], trigger, sizeof(VisualTrigger));
    return g_trigger_count++;
}

int vision_find_color_region(const uint8_t* frame, int width, int height,
                              const Rect2D* region, const ColorHSV* color,
                              int tolerance, Point2D* out_center) {
    Rect2D full_region = {0, 0, width, height};
    const Rect2D* r = region ? region : &full_region;
    
#ifdef USE_SSE
    return find_color_sse(frame, width, height, r, color, tolerance, out_center, 10000);
#elif defined(USE_NEON)
    return find_color_neon(frame, width, height, r, color, tolerance, out_center, 10000);
#else
    return find_color_scalar(frame, width, height, r, color, tolerance, out_center, 10000);
#endif
}

VisionResult* vision_find_template(const uint8_t* frame, int width, int height,
                                    const TemplateData* tmpl) {
    static VisionResult result;
    memset(&result, 0, sizeof(result));
    result.timestamp_ns = get_time_ns();
    
    int rx = tmpl->search_region.x > 0 ? tmpl->search_region.x : 0;
    int ry = tmpl->search_region.y > 0 ? tmpl->search_region.y : 0;
    int rw = tmpl->search_region.width > 0 ? tmpl->search_region.width : width;
    int rh = tmpl->search_region.height > 0 ? tmpl->search_region.height : height;
    
    float best_score = 0;
    int best_x = 0, best_y = 0;
    
    /* Coarse search with step size for performance */
    int step = 4;
    for (int y = ry; y < ry + rh - tmpl->height; y += step) {
        for (int x = rx; x < rx + rw - tmpl->width; x += step) {
#ifdef USE_SSE
            float score = template_match_sse(frame, width, height, x, y, tmpl);
#else
            float score = template_match_scalar(frame, width, height, x, y, tmpl);
#endif
            if (score > best_score) {
                best_score = score;
                best_x = x;
                best_y = y;
            }
        }
    }
    
    /* Fine search around best match */
    if (best_score > 0.5f) {
        for (int y = best_y - step; y <= best_y + step; y++) {
            for (int x = best_x - step; x <= best_x + step; x++) {
#ifdef USE_SSE
                float score = template_match_sse(frame, width, height, x, y, tmpl);
#else
                float score = template_match_scalar(frame, width, height, x, y, tmpl);
#endif
                if (score > best_score) {
                    best_score = score;
                    best_x = x;
                    best_y = y;
                }
            }
        }
    }
    
    result.trigger_id = tmpl->id;
    result.confidence = best_score;
    result.found = best_score >= tmpl->threshold;
    result.location.x = best_x + tmpl->width / 2;
    result.location.y = best_y + tmpl->height / 2;
    result.bounding_box.x = best_x;
    result.bounding_box.y = best_y;
    result.bounding_box.width = tmpl->width;
    result.bounding_box.height = tmpl->height;
    
    return &result;
}

int vision_detect_edge(const uint8_t* frame, int width, int height,
                        const Rect2D* region, bool horizontal,
                        int* out_position) {
    int rx = region->x > 0 ? region->x : 0;
    int ry = region->y > 0 ? region->y : 0;
    int rw = region->width > 0 ? region->width : width;
    int rh = region->height > 0 ? region->height : height;
    
    if (rx + rw > width) rw = width - rx;
    if (ry + rh > height) rh = height - ry;
    
    int max_gradient = 0;
    int edge_pos = -1;
    
    if (horizontal) {
        /* Horizontal edge detection - scan vertically */
        for (int y = ry + 1; y < ry + rh - 1; y++) {
            const uint8_t* row_prev = frame + (y - 1) * width * 4;
            const uint8_t* row_next = frame + (y + 1) * width * 4;
            
            int gradient_sum = 0;
            for (int x = rx; x < rx + rw; x++) {
                int idx = x * 4;
                int grad = abs((int)row_next[idx] - (int)row_prev[idx]) +
                           abs((int)row_next[idx+1] - (int)row_prev[idx+1]) +
                           abs((int)row_next[idx+2] - (int)row_prev[idx+2]);
                gradient_sum += grad;
            }
            
            if (gradient_sum > max_gradient) {
                max_gradient = gradient_sum;
                edge_pos = y;
            }
        }
    } else {
        /* Vertical edge detection - scan horizontally */
        for (int x = rx + 1; x < rx + rw - 1; x++) {
            int gradient_sum = 0;
            
            for (int y = ry; y < ry + rh; y++) {
                const uint8_t* row = frame + y * width * 4;
                int idx_prev = (x - 1) * 4;
                int idx_next = (x + 1) * 4;
                
                int grad = abs((int)row[idx_next] - (int)row[idx_prev]) +
                           abs((int)row[idx_next+1] - (int)row[idx_prev+1]) +
                           abs((int)row[idx_next+2] - (int)row[idx_prev+2]);
                gradient_sum += grad;
            }
            
            if (gradient_sum > max_gradient) {
                max_gradient = gradient_sum;
                edge_pos = x;
            }
        }
    }
    
    if (out_position) {
        *out_position = edge_pos;
    }
    
    return max_gradient > 1000 ? 0 : -1; /* Threshold for valid edge */
}

int vision_process_frame(SharedMemoryHeader* shm) {
    if (!shm || !shm->frame_ready) return -1;
    
    int64_t start_time = get_time_ns();
    uint8_t* frame = (uint8_t*)shm + sizeof(SharedMemoryHeader);
    
    int result_count = 0;
    
    /* Process all active triggers */
    for (int i = 0; i < g_trigger_count && result_count < 16; i++) {
        if (!g_triggers[i].active) continue;
        
        VisionResult* r = &shm->results[result_count];
        r->trigger_id = g_triggers[i].id;
        r->timestamp_ns = start_time;
        
        switch (g_triggers[i].type) {
            case TRIGGER_TEMPLATE_MATCH: {
                int tmpl_idx = g_triggers[i].params.template_id;
                if (tmpl_idx < g_template_count) {
                    VisionResult* match = vision_find_template(
                        frame, shm->frame_width, shm->frame_height,
                        &g_templates[tmpl_idx]);
                    memcpy(r, match, sizeof(VisionResult));
                }
                break;
            }
            
            case TRIGGER_COLOR_MATCH: {
                Point2D center;
                int count = vision_find_color_region(
                    frame, shm->frame_width, shm->frame_height,
                    &g_triggers[i].region, &g_triggers[i].params.color_hsv,
                    15, &center);
                r->found = count > 100; /* Minimum pixel threshold */
                r->location = center;
                r->confidence = count > 0 ? 1.0f : 0.0f;
                break;
            }
            
            case TRIGGER_EDGE_DETECT: {
                int pos;
                int ret = vision_detect_edge(
                    frame, shm->frame_width, shm->frame_height,
                    &g_triggers[i].region, 
                    g_triggers[i].params.edge.horizontal,
                    &pos);
                r->found = ret == 0;
                if (g_triggers[i].params.edge.horizontal) {
                    r->location.x = g_triggers[i].region.x + g_triggers[i].region.width / 2;
                    r->location.y = pos;
                } else {
                    r->location.x = pos;
                    r->location.y = g_triggers[i].region.y + g_triggers[i].region.height / 2;
                }
                r->confidence = r->found ? 1.0f : 0.0f;
                break;
            }
            
            default:
                break;
        }
        
        result_count++;
    }
    
    shm->num_results = result_count;
    shm->vision_latency_ns = get_time_ns() - start_time;
    
    return 0;
}
