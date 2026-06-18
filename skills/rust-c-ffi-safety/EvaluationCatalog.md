# Rust FFI Safety Evaluation Catalog for C Test Cases

This catalog is organized around the safety-critical FFI invariants emphasized by recent work on safe Rust interoperability: memory safety, aliasing XOR mutability, type safety / valid values, temporal safety, and concurrency. Omniglot explicitly frames foreign-value validation in terms of size, alignment, bit-pattern, and higher-level invariants, while SafeFFI highlights the raw-to-safe-pointer cast as the boundary where Rust-side guarantees must start to hold.

## Scope and conventions

* The goal of this catalog is to test **Rust-side FFI safety assumptions**, not only whether the C compiler accepts the program.
* Therefore, **“Illegal code” means “unsafe for the assumed Rust-side contract.”** Some illegal examples are also C undefined behavior, some are merely FFI contract violations, and some are ABI/layout mismatches.
* Each item states the **assumed Rust-side binding or expectation**. The same C code may be harmless under a weaker Rust binding but unsound under a stronger one.
* The catalog prioritizes **soundness-critical** items: valid values, pointer validity, ownership/lifetime, aliasing, temporal safety, and concurrency. This matches the main threat categories discussed in Omniglot and SafeFFI.

---

## 1. Invalid boolean bit pattern

**Description:** Writes a byte that Rust would later interpret as `bool`, but the byte is not `0` or `1`.

**Assumed Rust-side binding:** Rust reads the output byte as `bool`.

**Legal code:**

```c
#include <stdint.h>

void
fill_bool_legal(uint8_t *out) {
    *out = 1;
}
```

**Illegal code:**

```c
#include <stdint.h>

void
fill_bool_illegal(uint8_t *out) {
    *out = 2;
}
```

**Note:** Rust `bool` has only two valid values. Omniglot uses invalid `bool` as a canonical example of an FFI soundness violation.

---

## 2. Invalid Rust `char` value

**Description:** Produces a 32-bit value that is not a valid Rust `char`.

**Assumed Rust-side binding:** Rust reads the output as `char` or validates it as a Unicode scalar value.

**Legal code:**

```c
#include <stdint.h>

void
fill_char_legal(uint32_t *out) {
    *out = 0x0041; /* 'A' */
}
```

**Illegal code:**

```c
#include <stdint.h>

void
fill_char_illegal(uint32_t *out) {
    *out = 0xD800; /* surrogate, invalid Rust char */
}
```

**Note:** Omniglot explicitly mentions that a valid Rust `char` must be a valid non-surrogate Unicode scalar value.

---

## 3. Invalid enum discriminant

**Description:** Produces an integer outside the valid range of a Rust `#[repr(i32)]` enum.

**Assumed Rust-side binding:** Rust interprets the output as a `#[repr(i32)]` enum with only the values `0`, `1`, and `2`.

**Legal code:**

```c
#include <stdint.h>

void
fill_status_legal(int32_t *out) {
    *out = 1;
}
```

**Illegal code:**

```c
#include <stdint.h>

void
fill_status_illegal(int32_t *out) {
    *out = 99;
}
```

---

## 4. Null pointer for a non-null Rust type

**Description:** Returns `NULL` where Rust expects a non-null pointer-like type.

**Assumed Rust-side binding:** Rust binds this as `NonNull<i32>`, `&i32`, `&mut i32`, or another non-null pointer contract.

**Legal code:**

```c
static int value = 42;

int *
get_nonnull_ptr_legal(void) {
    return &value;
}
```

**Illegal code:**

```c
#include <stddef.h>

int *
get_nonnull_ptr_illegal(void) {
    return NULL;
}
```

---

## 5. Zero used for a non-zero Rust handle

**Description:** Returns zero for a handle that Rust models as `NonZeroU32` or equivalent.

**Assumed Rust-side binding:** Rust binds this as `core::num::NonZeroU32`.

**Legal code:**

```c
#include <stdint.h>

uint32_t
make_handle_legal(void) {
    return 1;
}
```

**Illegal code:**

```c
#include <stdint.h>

uint32_t
make_handle_illegal(void) {
    return 0;
}
```

---

## 6. Dangling heap pointer

**Description:** Returns a pointer that has already been freed.

**Assumed Rust-side binding:** Rust treats the returned pointer as live and dereferenceable.

**Legal code:**

```c
#include <stdlib.h>

int *
make_heap_ptr_legal(void) {
    int *p = (int *)malloc(sizeof(int));
    if (p == NULL) {
        return NULL;
    }
    *p = 42;
    return p;
}
```

**Illegal code:**

```c
#include <stdlib.h>

int *
make_heap_ptr_illegal(void) {
    int *p = (int *)malloc(sizeof(int));
    if (p == NULL) {
        return NULL;
    }
    *p = 42;
    free(p);
    return p;
}
```

---

## 7. Returning the address of a stack local

**Description:** Returns a pointer to stack memory that becomes invalid when the function returns.

**Assumed Rust-side binding:** Rust dereferences the returned pointer after the call.

**Legal code:**

```c
static int value = 42;

int *
return_static_ptr_legal(void) {
    return &value;
}
```

**Illegal code:**

```c
int *
return_stack_ptr_illegal(void) {
    int value = 42;
    return &value;
}
```

---

## 8. Misaligned pointer

**Description:** Returns a pointer that is not properly aligned for its pointee type.

**Assumed Rust-side binding:** Rust dereferences the returned pointer as `*const uint32_t` or creates `&u32` from it.

**Legal code:**

```c
#include <stdint.h>

const uint32_t *
pass_through_u32_ptr_legal(const uint32_t *p) {
    return p;
}
```

**Illegal code:**

```c
#include <stdint.h>

const uint32_t *
make_misaligned_ptr_illegal(const uint8_t *buf) {
    return (const uint32_t *)(buf + 1);
}
```

**Note:** Omniglot explicitly lists misaligned accesses among the soundness conditions foreign code must not violate.

---

## 9. Out-of-bounds pointer

**Description:** Returns a pointer outside the referenced allocation.

**Assumed Rust-side binding:** Rust assumes the pointer points into a valid object or slice.

**Legal code:**

```c
#include <stdint.h>

const uint8_t *
get_in_bounds_ptr_legal(void) {
    static uint8_t data[4] = {1, 2, 3, 4};
    return &data[0];
}
```

**Illegal code:**

```c
#include <stdint.h>

const uint8_t *
get_out_of_bounds_ptr_illegal(void) {
    static uint8_t data[4] = {1, 2, 3, 4};
    return data + 8;
}
```

---

## 10. Slice length larger than the pointed allocation

**Description:** Returns `(ptr, len)` metadata that overstates the accessible allocation.

**Assumed Rust-side binding:** Rust reconstructs a slice from the pair.

**Legal code:**

```c
#include <stddef.h>
#include <stdint.h>

struct ByteSlice {
    const uint8_t *ptr;
    size_t len;
};

struct ByteSlice
get_slice_legal(void) {
    static uint8_t data[4] = {1, 2, 3, 4};
    return (struct ByteSlice){ data, 4 };
}
```

**Illegal code:**

```c
#include <stddef.h>
#include <stdint.h>

struct ByteSlice {
    const uint8_t *ptr;
    size_t len;
};

struct ByteSlice
get_slice_illegal(void) {
    static uint8_t data[4] = {1, 2, 3, 4};
    return (struct ByteSlice){ data, 1024 };
}
```

---

## 11. Forged pointer from an arbitrary integer

**Description:** Constructs a pointer value that does not come from a valid live allocation.

**Assumed Rust-side binding:** Rust treats the returned pointer as valid memory.

**Legal code:**

```c
#include <stdint.h>

int *
make_pointer_from_roundtrip_legal(void) {
    static int value = 42;
    uintptr_t raw = (uintptr_t)&value;
    return (int *)raw;
}
```

**Illegal code:**

```c
#include <stdint.h>

int *
make_forged_pointer_illegal(void) {
    return (int *)(uintptr_t)0x1;
}
```

---

## 12. Borrowed input retained after the call

**Description:** Stores a borrowed input pointer for later use, even though the Rust side may have passed only a temporary borrow.

**Assumed Rust-side binding:** Rust passes a pointer valid only for the duration of the call.

**Legal code:**

```c
#include <stddef.h>
#include <stdint.h>

void
observe_input_legal(const uint8_t *p, size_t len) {
    (void)p;
    (void)len;
}
```

**Illegal code:**

```c
#include <stddef.h>
#include <stdint.h>

static const uint8_t *saved_ptr;
static size_t saved_len;

void
observe_input_illegal(const uint8_t *p, size_t len) {
    saved_ptr = p;
    saved_len = len;
}

uint8_t
read_saved_illegal(void) {
    return saved_ptr[0];
}
```

---

## 13. Function claims to return owned heap memory but returns static storage

**Description:** Violates the ownership/allocator contract of the return value.

**Assumed Rust-side binding:** Rust treats the returned pointer as owned memory that must later be freed through the C-side deallocator.

**Legal code:**

```c
#include <stdlib.h>
#include <string.h>

char *
make_owned_string_legal(void) {
    char *p = (char *)malloc(6);
    if (p == NULL) {
        return NULL;
    }
    memcpy(p, "hello", 6);
    return p;
}
```

**Illegal code:**

```c
char *
make_owned_string_illegal(void) {
    static char s[] = "hello";
    return s;
}
```

---

## 14. Success return without initializing the out-parameter

**Description:** Reports success but leaves output memory uninitialized.

**Assumed Rust-side binding:** On success, Rust immediately reads the out-parameter.

**Legal code:**

```c
#include <stdint.h>

int
compute_value_legal(uint32_t *out) {
    *out = 1234;
    return 1;
}
```

**Illegal code:**

```c
#include <stdint.h>

int
compute_value_illegal(uint32_t *out) {
    (void)out;
    return 1;
}
```

---

## 15. Struct packing/alignment mismatch

**Description:** Uses a packed C layout where Rust expects a normal `#[repr(C)]` layout.

**Assumed Rust-side binding:** Rust expects the natural C layout of `struct Pair`.

**Legal code:**

```c
#include <stdint.h>

struct Pair {
    uint32_t tag;
    uint64_t value;
};

struct Pair
make_pair_legal(void) {
    return (struct Pair){ 1, 0x1122334455667788ULL };
}
```

**Illegal code:**

```c
#include <stdint.h>

#pragma pack(push, 1)
struct Pair {
    uint32_t tag;
    uint64_t value;
};
#pragma pack(pop)

struct Pair
make_pair_illegal(void) {
    return (struct Pair){ 1, 0x1122334455667788ULL };
}
```

---

## 16. Struct field order mismatch

**Description:** Uses the same field types but a different field order than Rust expects.

**Assumed Rust-side binding:** Rust expects `struct Header { uint32_t tag; uint32_t len; }`.

**Legal code:**

```c
#include <stdint.h>

struct Header {
    uint32_t tag;
    uint32_t len;
};

struct Header
make_header_legal(void) {
    return (struct Header){ 7, 16 };
}
```

**Illegal code:**

```c
#include <stdint.h>

struct Header {
    uint32_t len;
    uint32_t tag;
};

struct Header
make_header_illegal(void) {
    return (struct Header){ 16, 7 };
}
```

---

## 17. Mutable and shared alias to the same memory

**Description:** Returns an immutable-looking output that aliases the mutable input buffer.

**Assumed Rust-side binding:** Rust holds a mutable borrow of `src` and also creates a shared borrow from `*dst`.

**Legal code:**

```c
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

void
separate_output_legal(uint8_t *src, size_t len, const uint8_t **dst) {
    uint8_t *p = (uint8_t *)malloc(len);
    if (p == NULL) {
        *dst = NULL;
        return;
    }
    memcpy(p, src, len);
    *dst = p;
}
```

**Illegal code:**

```c
#include <stddef.h>
#include <stdint.h>

void
in_place_alias_illegal(uint8_t *src, size_t len, const uint8_t **dst) {
    (void)len;
    *dst = src;
}
```

**Note:** Omniglot uses essentially this pattern as a motivating aliasing XOR mutability violation.

---

## 18. Two mutable aliases to the same memory

**Description:** Produces two writable pointers that actually point to the same object.

**Assumed Rust-side binding:** Rust treats the two outputs as distinct mutable borrows.

**Legal code:**

```c
#include <stdint.h>

void
split_mut_legal(uint8_t **a, uint8_t **b) {
    static uint8_t x = 1;
    static uint8_t y = 2;
    *a = &x;
    *b = &y;
}
```

**Illegal code:**

```c
#include <stdint.h>

void
split_mut_illegal(uint8_t **a, uint8_t **b) {
    static uint8_t x = 1;
    *a = &x;
    *b = &x;
}
```

---

## 19. Mutation through a nominally immutable input

**Description:** Receives a read-only input pointer but writes through it anyway.

**Assumed Rust-side binding:** Rust passed a shared borrow (for example, `&[u8]` or `&T`) and assumes the callee will not mutate it.

**Legal code:**

```c
#include <stddef.h>
#include <stdint.h>

uint8_t
read_only_sum_legal(const uint8_t *p, size_t len) {
    size_t i;
    uint8_t sum = 0;
    for (i = 0; i < len; i++) {
        sum = (uint8_t)(sum + p[i]);
    }
    return sum;
}
```

**Illegal code:**

```c
#include <stddef.h>
#include <stdint.h>

void
write_through_const_illegal(const uint8_t *p, size_t len) {
    if (len > 0) {
        ((uint8_t *)p)[0] = 0xFF;
    }
}
```

---

## 20. Concurrent background mutation after the call returns

**Description:** Spawns a background thread that continues mutating shared memory after the FFI call returns.

**Assumed Rust-side binding:** Rust may validate or borrow the memory after the function returns, assuming no uncoordinated concurrent mutation.

**Legal code:**

```c
#include <stdint.h>

void
no_background_mutation_legal(uint8_t *p) {
    p[0] ^= 0x01;
}
```

**Illegal code:**

```c
#include <pthread.h>
#include <stdint.h>
#include <unistd.h>

static void *
writer_thread(void *arg) {
    uint8_t *p = (uint8_t *)arg;
    usleep(1000);
    p[0] ^= 0xFF;
    return NULL;
}

void
start_background_mutation_illegal(uint8_t *p) {
    pthread_t t;
    pthread_create(&t, NULL, writer_thread, p);
    pthread_detach(t);
}
```

**Note:** Omniglot explicitly treats concurrent foreign mutation as a source of unsoundness and requires preventing foreign code from continuing in the background.

---

## 21. Asynchronous mutation via a signal handler

**Description:** Mutates shared memory asynchronously through a signal handler after Rust may have validated it.

**Assumed Rust-side binding:** Rust assumes the memory stays unchanged except through explicit coordination.

**Legal code:**

```c
#include <stdint.h>

void
no_async_mutation_legal(uint8_t *p) {
    p[0] ^= 0x01;
}
```

**Illegal code:**

```c
#include <signal.h>
#include <stdint.h>

static uint8_t *global_ptr;

static void
handler(int signo) {
    (void)signo;
    global_ptr[0] = 0x42;
}

void
async_signal_mutation_illegal(uint8_t *p) {
    global_ptr = p;
    signal(SIGUSR1, handler);
    raise(SIGUSR1);
}
```

---

## 22. `longjmp` across the FFI boundary

**Description:** Escapes control flow non-locally instead of returning normally.

**Assumed Rust-side binding:** Rust expects the foreign function to return normally and not bypass Rust frames.

**Legal code:**

```c
int
foreign_call_legal(void) {
    return -1; /* ordinary error return */
}
```

**Illegal code:**

```c
#include <setjmp.h>

static jmp_buf env;

void
set_env_for_demo(void) {
    (void)setjmp(env);
}

void
foreign_call_illegal(void) {
    longjmp(env, 1);
}
```

**Note:** Omniglot discusses the need to constrain foreign execution and callbacks so that Rust-side invariants are not invalidated by unexpected control flow or temporal effects.

---

## 23. Invalid UTF-8 for a Rust `str`

**Description:** Produces bytes that are fine as raw C bytes or as a C string, but not valid UTF-8 for Rust `str`.

**Assumed Rust-side binding:** Rust converts the returned bytes directly to `str` or otherwise assumes UTF-8.

**Legal code:**

```c
const char *
get_utf8_legal(void) {
    return "hello";
}
```

**Illegal code:**

```c
const char *
get_utf8_illegal(void) {
    static const char s[] = { (char)0xFF, 0 };
    return s;
}
```

**Note:** Omniglot explicitly cites UTF-8 validity as a high-level Rust invariant that ordinary C ABI bindings do not capture.

---

## 24. Uninitialized scalar value

**Description:** Exposes an uninitialized scalar value to Rust.

**Assumed Rust-side binding:** Rust reads the scalar immediately as a valid initialized value.

**Legal code:**

```c
#include <stdint.h>

uint32_t
get_initialized_u32_legal(void) {
    uint32_t x = 1234;
    return x;
}
```

**Illegal code:**

```c
#include <stdint.h>

uint32_t
get_uninitialized_u32_illegal(void) {
    uint32_t x;
    return x;
}
```

---

## 25. Overlapping buffers where Rust assumes non-overlap

**Description:** Performs an operation under a non-overlap contract, but the actual inputs overlap.

**Assumed Rust-side binding:** Rust wrapper assumes input and output regions are disjoint.

**Legal code:**

```c
#include <stddef.h>
#include <string.h>

void
copy_nonoverlap_legal(unsigned char *dst, const unsigned char *src, size_t len) {
    memcpy(dst, src, len);
}
```

**Illegal code:**

```c
#include <stddef.h>
#include <string.h>

void
copy_nonoverlap_illegal(unsigned char *buf, size_t len) {
    memcpy(buf + 1, buf, len); /* overlapping source and destination */
}
```

---

## 26. Pointer-sized integer used with the wrong provenance/ownership meaning

**Description:** Reuses a numeric handle as though it were still a valid pointer to the same live object.

**Assumed Rust-side binding:** Rust interprets the integer as a live pointer or trusted handle to current memory.

**Legal code:**

```c
#include <stdint.h>

uintptr_t
export_live_pointer_legal(void) {
    static int value = 42;
    return (uintptr_t)&value;
}
```

**Illegal code:**

```c
#include <stdint.h>
#include <stdlib.h>

uintptr_t
export_stale_pointer_illegal(void) {
    int *p = (int *)malloc(sizeof(int));
    if (p == NULL) {
        return 0;
    }
    *p = 42;
    uintptr_t raw = (uintptr_t)p;
    free(p);
    return raw;
}
```

---

# Suggested grouping for evaluation

A practical test suite can group the items above into the following classes:

1. **Valid-value violations**

   * 1, 2, 3, 5, 23, 24

2. **Pointer validity violations**

   * 4, 6, 7, 8, 9, 10, 11, 26

3. **Ownership and lifetime violations**

   * 12, 13, 14

4. **Layout / ABI violations**

   * 15, 16

5. **Aliasing XOR mutability violations**

   * 17, 18, 19, 25

6. **Temporal / concurrency / control-flow violations**

   * 20, 21, 22

# Recommended metadata fields per test case

For each test case, it is useful to store the following metadata in addition to the code:

* `id`
* `title`
* `description`
* `assumed_rust_binding`
* `category`
* `violation_kind`

  * `ffi_contract_violation`
  * `c_ub`
  * `abi_mismatch`
  * `concurrency_violation`
* `expected_effect`

  * `invalid_value`
  * `dangling_pointer`
  * `misaligned_pointer`
  * `aliasing_violation`
  * `temporal_violation`
  * `layout_mismatch`
* `legal_code`
* `illegal_code`

# Short rationale

This catalog is designed to match what recent Rust FFI safety work treats as the core problem: **the C ABI by itself does not preserve Rust’s safety invariants**, so foreign data and pointers must be checked against Rust-side requirements concerning valid values, memory safety, aliasing, and concurrency.   SafeFFI complements that view by focusing on the precise boundary where raw pointers become Rust-safe pointers, which is why many items in this catalog are naturally phrased as “legal under a weak C/raw-pointer view, illegal under the stronger Rust-side interpretation.”

