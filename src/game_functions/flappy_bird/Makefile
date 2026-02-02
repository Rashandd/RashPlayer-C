# Flappy Bird Game Functions - C Library Build
# Compiles high-performance detection functions

CC = gcc
CFLAGS = -O3 -fPIC -Wall -Wextra -march=native -ffast-math
LDFLAGS = -shared -lm

# Platform detection
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Linux)
    TARGET = libgame_functions.so
endif
ifeq ($(UNAME_S),Darwin)
    TARGET = libgame_functions.dylib
endif
ifeq ($(OS),Windows_NT)
    TARGET = game_functions.dll
    CC = gcc
endif

# Default target
TARGET ?= libgame_functions.so

SRC = game_functions.c
OBJ = $(SRC:.c=.o)

.PHONY: all clean

all: $(TARGET)
	@echo "✓ Built $(TARGET)"

$(TARGET): $(OBJ)
	$(CC) $(LDFLAGS) -o $@ $^

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJ) $(TARGET)

# Install to system (optional)
install: $(TARGET)
	cp $(TARGET) /usr/local/lib/
	ldconfig

# Debug build
debug: CFLAGS = -g -O0 -fPIC -Wall -Wextra
debug: clean all
