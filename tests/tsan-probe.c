/* SPDX-License-Identifier: Apache-2.0 */
/* Intentional race: the TSan validation driver must detect this before testing. */
#include <assert.h>
#include <pthread.h>
static volatile int value;
static void *increment(void *p) { (void)p; ++value; return NULL; }
int main(void) {
    pthread_t a,b;
    assert(!pthread_create(&a,NULL,increment,NULL));
    assert(!pthread_create(&b,NULL,increment,NULL));
    assert(!pthread_join(a,NULL) && !pthread_join(b,NULL));
    return 0;
}
