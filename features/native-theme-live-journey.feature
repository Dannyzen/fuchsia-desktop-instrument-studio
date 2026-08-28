@native-theme @p3
Feature: Choose a NativeTheme and keep it across restart
  The read-only authority is delivered before Settings owns mutation and persistence.

  @implemented @p3-s1 @scenario:P3S1-READ-ONLY
  Scenario: Consumers can discover packaged themes without mutation authority
    Given the NativeTheme authority starts with its packaged catalog
    Then a consumer can list theme metadata and read the immutable active snapshot
    And the consumer protocol has no method that selects or persists a theme

  @implemented @p3-s1 @scenario:P3S1-WATCH
  Scenario: Independent consumers watch the active generation
    Given two consumer connections have observed the current generation
    When both watch that same generation
    Then both calls remain pending until a strictly newer generation exists
    And any generation unequal to the current process generation returns immediately
    And a reconnected consumer calls GetCurrent before watching the new process generation

  @implemented @p3-s1 @scenario:P3S1-FALLBACK
  Scenario: Invalid packaged data uses the built-in fallback
    Given packaged theme data is invalid
    When the NativeTheme authority starts
    Then generation zero identifies the built-in fallback
    And bounded diagnostics record a validation failure without payload bytes or paths

  @implemented @p3-s1 @scenario:P3S1-OPTIONAL
  Scenario: Shell boot does not require the NativeTheme authority
    Given the NativeTheme authority is unavailable
    When the workbench shell starts
    Then its optional consumer route does not block shell startup
    And consumers retain their built-in fallback

  @planned @p3-s2
  Scenario: Settings stores the named theme for the next restart
    Given Settings is the sole writer of a named catalog identity for the next restart
    When writing a newly chosen identity succeeds
    Then it replaces the prior selection
    But a failed write preserves the prior selection

  @planned @p4
  Scenario: Apply and Restart makes the chosen theme visible
    Given the user chooses a named theme in Settings
    When the user invokes Apply and Restart
    Then the shell and applications visibly consume the selected semantic snapshot

  @planned @p6
  Scenario: The chosen theme survives a full product restart
    Given Apply and Restart made the chosen theme visible
    When the full product restarts
    Then the same theme remains selected and visible

  @planned @p6 @recovery
  Scenario: Invalid persisted state cannot prevent shell boot
    Given persisted state is corrupt or unknown, or its theme pack is missing
    When the full product starts
    Then selection recovers to the last-known-good or built-in theme
    And the shell still boots
