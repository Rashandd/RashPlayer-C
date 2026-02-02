/*
 * RashPlayer-C: Logic Brain
 * Copyright (c) 2026 RashPlayer Project
 * 
 * Finite State Machine for game state processing and decision making
 * Processes vision results and generates action commands
 */

#include "../include/shared_bridge.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <ctype.h>

/* ============================================================================
 * INTERNAL STATE
 * ========================================================================= */

#define MAX_RULES 256
#define MAX_VARIABLES 64

typedef struct {
    char    name[32];
    int32_t value;
} Variable;

static DecisionRule     g_rules[MAX_RULES];
static int              g_rule_count = 0;
static Variable         g_variables[MAX_VARIABLES];
static int              g_variable_count = 0;
static GameState        g_current_state = GAME_STATE_IDLE;
static bool             g_brain_initialized = false;
static int              g_polling_hz = 60;

/* ============================================================================
 * UTILITY FUNCTIONS
 * ========================================================================= */

static int64_t get_time_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

/* Set a named variable */
static int set_variable(const char* name, int32_t value) {
    /* Look for existing variable */
    for (int i = 0; i < g_variable_count; i++) {
        if (strcmp(g_variables[i].name, name) == 0) {
            g_variables[i].value = value;
            return 0;
        }
    }
    
    /* Add new variable */
    if (g_variable_count >= MAX_VARIABLES) return -1;
    
    strncpy(g_variables[g_variable_count].name, name, 31);
    g_variables[g_variable_count].name[31] = '\0';
    g_variables[g_variable_count].value = value;
    g_variable_count++;
    
    return 0;
}

/* Get a named variable */
static int32_t get_variable(const char* name) {
    for (int i = 0; i < g_variable_count; i++) {
        if (strcmp(g_variables[i].name, name) == 0) {
            return g_variables[i].value;
        }
    }
    return 0;
}

/* ============================================================================
 * EXPRESSION PARSER
 * Simple parser for conditions like "bird_y > gap_center_y + 20"
 * ========================================================================= */

typedef enum {
    TOKEN_NUMBER,
    TOKEN_VARIABLE,
    TOKEN_OP_GT,    /* > */
    TOKEN_OP_LT,    /* < */
    TOKEN_OP_GE,    /* >= */
    TOKEN_OP_LE,    /* <= */
    TOKEN_OP_EQ,    /* == */
    TOKEN_OP_NE,    /* != */
    TOKEN_OP_ADD,   /* + */
    TOKEN_OP_SUB,   /* - */
    TOKEN_OP_AND,   /* && */
    TOKEN_OP_OR,    /* || */
    TOKEN_END
} TokenType;

typedef struct {
    TokenType   type;
    int32_t     num_value;
    char        str_value[32];
} Token;

static const char* tokenize(const char* expr, Token* token) {
    /* Skip whitespace */
    while (*expr && isspace(*expr)) expr++;
    
    if (!*expr) {
        token->type = TOKEN_END;
        return expr;
    }
    
    /* Number */
    if (isdigit(*expr) || (*expr == '-' && isdigit(*(expr+1)))) {
        token->type = TOKEN_NUMBER;
        token->num_value = strtol(expr, (char**)&expr, 10);
        return expr;
    }
    
    /* Operators */
    if (expr[0] == '>' && expr[1] == '=') {
        token->type = TOKEN_OP_GE;
        return expr + 2;
    }
    if (expr[0] == '<' && expr[1] == '=') {
        token->type = TOKEN_OP_LE;
        return expr + 2;
    }
    if (expr[0] == '=' && expr[1] == '=') {
        token->type = TOKEN_OP_EQ;
        return expr + 2;
    }
    if (expr[0] == '!' && expr[1] == '=') {
        token->type = TOKEN_OP_NE;
        return expr + 2;
    }
    if (expr[0] == '&' && expr[1] == '&') {
        token->type = TOKEN_OP_AND;
        return expr + 2;
    }
    if (expr[0] == '|' && expr[1] == '|') {
        token->type = TOKEN_OP_OR;
        return expr + 2;
    }
    if (*expr == '>') {
        token->type = TOKEN_OP_GT;
        return expr + 1;
    }
    if (*expr == '<') {
        token->type = TOKEN_OP_LT;
        return expr + 1;
    }
    if (*expr == '+') {
        token->type = TOKEN_OP_ADD;
        return expr + 1;
    }
    if (*expr == '-') {
        token->type = TOKEN_OP_SUB;
        return expr + 1;
    }
    
    /* Variable name */
    if (isalpha(*expr) || *expr == '_') {
        token->type = TOKEN_VARIABLE;
        int i = 0;
        while ((isalnum(*expr) || *expr == '_') && i < 31) {
            token->str_value[i++] = *expr++;
        }
        token->str_value[i] = '\0';
        return expr;
    }
    
    token->type = TOKEN_END;
    return expr;
}

/* Evaluate a simple expression and return the result */
static int32_t eval_value(const char** expr) {
    Token token;
    *expr = tokenize(*expr, &token);
    
    int32_t value = 0;
    if (token.type == TOKEN_NUMBER) {
        value = token.num_value;
    } else if (token.type == TOKEN_VARIABLE) {
        value = get_variable(token.str_value);
    }
    
    /* Check for arithmetic operators */
    Token op;
    const char* saved = *expr;
    *expr = tokenize(*expr, &op);
    
    if (op.type == TOKEN_OP_ADD) {
        value += eval_value(expr);
    } else if (op.type == TOKEN_OP_SUB) {
        value -= eval_value(expr);
    } else {
        *expr = saved; /* Put back the token */
    }
    
    return value;
}

/* Evaluate a condition string, returns 1 if true, 0 if false */
static int eval_condition(const char* condition) {
    int32_t left = eval_value(&condition);
    
    Token op;
    condition = tokenize(condition, &op);
    
    if (op.type == TOKEN_END) {
        return left != 0;
    }
    
    int32_t right = eval_value(&condition);
    
    int result = 0;
    switch (op.type) {
        case TOKEN_OP_GT: result = left > right; break;
        case TOKEN_OP_LT: result = left < right; break;
        case TOKEN_OP_GE: result = left >= right; break;
        case TOKEN_OP_LE: result = left <= right; break;
        case TOKEN_OP_EQ: result = left == right; break;
        case TOKEN_OP_NE: result = left != right; break;
        default: break;
    }
    
    /* Check for AND/OR */
    Token logical;
    const char* saved = condition;
    condition = tokenize(condition, &logical);
    
    if (logical.type == TOKEN_OP_AND) {
        return result && eval_condition(condition);
    } else if (logical.type == TOKEN_OP_OR) {
        return result || eval_condition(condition);
    }
    
    return result;
}

/* ============================================================================
 * FSM STATE TRANSITIONS
 * ========================================================================= */

static const char* state_name(GameState state) {
    switch (state) {
        case GAME_STATE_IDLE: return "IDLE";
        case GAME_STATE_DETECTING: return "DETECTING";
        case GAME_STATE_ACTION_PENDING: return "ACTION_PENDING";
        case GAME_STATE_EXECUTING: return "EXECUTING";
        case GAME_STATE_PAUSED: return "PAUSED";
        case GAME_STATE_ERROR: return "ERROR";
        default: return "UNKNOWN";
    }
}

static GameState fsm_transition(GameState current, int vision_results, int action_pending) {
    switch (current) {
        case GAME_STATE_IDLE:
            if (vision_results > 0) {
                return GAME_STATE_DETECTING;
            }
            break;
            
        case GAME_STATE_DETECTING:
            if (action_pending) {
                return GAME_STATE_ACTION_PENDING;
            }
            if (vision_results == 0) {
                return GAME_STATE_IDLE;
            }
            break;
            
        case GAME_STATE_ACTION_PENDING:
            return GAME_STATE_EXECUTING;
            
        case GAME_STATE_EXECUTING:
            return GAME_STATE_DETECTING;
            
        case GAME_STATE_PAUSED:
            /* Stay paused until explicitly resumed */
            break;
            
        case GAME_STATE_ERROR:
            /* Stay in error until reset */
            break;
    }
    
    return current;
}

/* ============================================================================
 * PUBLIC API IMPLEMENTATION
 * ========================================================================= */

int brain_init(void) {
    if (g_brain_initialized) return 0;
    
    memset(g_rules, 0, sizeof(g_rules));
    memset(g_variables, 0, sizeof(g_variables));
    g_rule_count = 0;
    g_variable_count = 0;
    g_current_state = GAME_STATE_IDLE;
    g_brain_initialized = true;
    
    return 0;
}

void brain_shutdown(void) {
    g_rule_count = 0;
    g_variable_count = 0;
    g_current_state = GAME_STATE_IDLE;
    g_brain_initialized = false;
}

int brain_load_rules(const DecisionRule* rules, int count) {
    if (!rules || count <= 0 || count > MAX_RULES) {
        return -1;
    }
    
    memcpy(g_rules, rules, count * sizeof(DecisionRule));
    g_rule_count = count;
    
    return 0;
}

int brain_set_state(GameState state) {
    g_current_state = state;
    return 0;
}

GameState brain_get_state(void) {
    return g_current_state;
}

ActionCommand* brain_evaluate(const VisionResult* results, int count) {
    static ActionCommand action;
    memset(&action, 0, sizeof(action));
    action.type = ACTION_NONE;
    
    if (!results || count <= 0) {
        return &action;
    }
    
    /* Update variables from vision results */
    for (int i = 0; i < count; i++) {
        if (results[i].found) {
            char var_x[64], var_y[64], var_found[64];
            snprintf(var_x, sizeof(var_x), "trigger_%u_x", results[i].trigger_id);
            snprintf(var_y, sizeof(var_y), "trigger_%u_y", results[i].trigger_id);
            snprintf(var_found, sizeof(var_found), "trigger_%u_found", results[i].trigger_id);
            
            set_variable(var_x, results[i].location.x);
            set_variable(var_y, results[i].location.y);
            set_variable(var_found, 1);
            
            /* Also set by name if trigger_id maps to common names */
            /* TODO: Add trigger name mapping */
            
            /* Special handling for common game elements */
            if (results[i].trigger_id == 1) { /* Bird */
                set_variable("bird_x", results[i].location.x);
                set_variable("bird_y", results[i].location.y);
            } else if (results[i].trigger_id == 2) { /* Gap */
                set_variable("gap_center_x", results[i].location.x);
                set_variable("gap_center_y", results[i].location.y);
            }
        }
    }
    
    /* Evaluate rules by priority (highest first) */
    int best_priority = -1;
    const DecisionRule* best_rule = NULL;
    
    for (int i = 0; i < g_rule_count; i++) {
        if (g_rules[i].priority > best_priority) {
            if (eval_condition(g_rules[i].condition)) {
                best_priority = g_rules[i].priority;
                best_rule = &g_rules[i];
            }
        }
    }
    
    if (best_rule) {
        action.type = best_rule->action;
        action.start = best_rule->action_target;
        action.duration_ms = 50; /* Default tap duration */
        action.randomize = 0.3f; /* 30% randomization */
    }
    
    return &action;
}

int brain_process(SharedMemoryHeader* shm) {
    if (!shm) return -1;
    
    int64_t start_time = get_time_ns();
    
    /* Update FSM state based on vision results */
    int has_results = shm->num_results > 0;
    for (uint32_t i = 0; i < shm->num_results; i++) {
        if (!shm->results[i].found) {
            has_results = 0;
            break;
        }
    }
    
    /* Evaluate decision rules */
    ActionCommand* action = brain_evaluate(shm->results, shm->num_results);
    int action_pending = action->type != ACTION_NONE;
    
    /* Transition FSM */
    GameState new_state = fsm_transition(g_current_state, has_results, action_pending);
    if (new_state != g_current_state) {
        g_current_state = new_state;
    }
    
    /* Copy action to shared memory if pending */
    if (action_pending && g_current_state == GAME_STATE_ACTION_PENDING) {
        memcpy(&shm->pending_action, action, sizeof(ActionCommand));
    }
    
    shm->current_state = g_current_state;
    shm->brain_latency_ns = get_time_ns() - start_time;
    shm->total_latency_ns = shm->vision_latency_ns + shm->brain_latency_ns;
    shm->result_ready = 1;
    
    return 0;
}

/* ============================================================================
 * MAIN PROCESSING LOOP (for standalone testing)
 * ========================================================================= */

#ifdef BRAIN_STANDALONE

#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>

extern int vision_init(void);
extern void vision_shutdown(void);
extern int vision_process_frame(SharedMemoryHeader* shm);

int main(int argc, char* argv[]) {
    printf("RashPlayer-C Logic Brain v1.0\n");
    printf("Initializing...\n");
    
    /* Open shared memory */
    int shm_fd = shm_open(RASHPLAYER_SHM_NAME, O_RDWR, 0666);
    if (shm_fd < 0) {
        perror("shm_open failed");
        return 1;
    }
    
    SharedMemoryHeader* shm = (SharedMemoryHeader*)mmap(
        NULL, RASHPLAYER_SHM_SIZE, PROT_READ | PROT_WRITE,
        MAP_SHARED, shm_fd, 0);
    
    if (shm == MAP_FAILED) {
        perror("mmap failed");
        close(shm_fd);
        return 1;
    }
    
    /* Initialize engines */
    vision_init();
    brain_init();
    
    printf("Processing loop started (100Hz)...\n");
    
    int64_t loop_interval_ns = 1000000000LL / 100; /* 100Hz = 10ms */
    
    while (1) {
        int64_t loop_start = get_time_ns();
        
        if (shm->frame_ready) {
            /* Process vision */
            vision_process_frame(shm);
            
            /* Process brain */
            brain_process(shm);
            
            /* Clear frame ready flag */
            shm->frame_ready = 0;
            
            printf("Frame %lu: Vision=%ldus, Brain=%ldus, Total=%ldus, State=%s\n",
                   shm->frame_number,
                   shm->vision_latency_ns / 1000,
                   shm->brain_latency_ns / 1000,
                   shm->total_latency_ns / 1000,
                   state_name(shm->current_state));
        }
        
        /* Sleep for remaining time */
        int64_t elapsed = get_time_ns() - loop_start;
        if (elapsed < loop_interval_ns) {
            struct timespec ts;
            ts.tv_sec = 0;
            ts.tv_nsec = loop_interval_ns - elapsed;
            nanosleep(&ts, NULL);
        }
    }
    
    /* Cleanup */
    vision_shutdown();
    brain_shutdown();
    munmap(shm, RASHPLAYER_SHM_SIZE);
    close(shm_fd);
    
    return 0;
}

#endif /* BRAIN_STANDALONE */
