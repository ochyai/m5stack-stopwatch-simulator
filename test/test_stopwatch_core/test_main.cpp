#include <unity.h>

#include "../../firmware/shared/helpers.hpp"
#include "../../firmware/shared/stopwatch_core.hpp"

void test_initial_state_is_stopped_at_zero() {
  c152::StopwatchCore timer;
  TEST_ASSERT_FALSE(timer.isRunning());
  TEST_ASSERT_EQUAL_UINT64(0, timer.elapsedUs(123456));
}
void test_start_pause_and_resume_accumulates_time() {
  c152::StopwatchCore timer;
  timer.toggle(1000);
  TEST_ASSERT_TRUE(timer.isRunning());
  TEST_ASSERT_EQUAL_UINT64(2500, timer.elapsedUs(3500));

  timer.toggle(4000);
  TEST_ASSERT_FALSE(timer.isRunning());
  TEST_ASSERT_EQUAL_UINT64(3000, timer.elapsedUs(9000));

  timer.toggle(10000);
  TEST_ASSERT_EQUAL_UINT64(3500, timer.elapsedUs(10500));
}

void test_reset_stops_and_clears() {
  c152::StopwatchCore timer;
  timer.toggle(100);
  timer.reset(500);
  TEST_ASSERT_FALSE(timer.isRunning());
  TEST_ASSERT_EQUAL_UINT64(0, timer.elapsedUs(1000));
}

void test_duration_format() {
  char output[24];
  c152::formatElapsed(3723000000ULL, output, sizeof(output));
  TEST_ASSERT_EQUAL_STRING("01:02:03.00", output);
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_initial_state_is_stopped_at_zero);
  RUN_TEST(test_start_pause_and_resume_accumulates_time);
  RUN_TEST(test_reset_stops_and_clears);
  RUN_TEST(test_duration_format);
  return UNITY_END();
}
