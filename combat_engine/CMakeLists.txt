cmake_minimum_required(VERSION 3.19)
project(sts_ironclad_engine LANGUAGES CXX)

# Builds the teacher and original-game Python entries from the combat4r snapshot:
#   slaythespire  - simulator core + bindings
#   fightsim      - fight simulation / search driver (combat4r/agent/fightsim.cpp)
#   live_combat_search - original-game state/queue import + BattleContext search
# All are written to ${STS_RUNTIME_DIR}/engine (default: <repo>/runtime/engine).

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# Asserts stay on: the search relies on them for invariant checks.
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -UNDEBUG")
add_compile_definitions(COMBAT3_TARGET_POLICY=1)

find_package(pybind11 CONFIG REQUIRED)

set(SRC ${CMAKE_CURRENT_SOURCE_DIR}/combat4r/engine-source)
set(AGENT ${CMAKE_CURRENT_SOURCE_DIR}/combat4r/agent)
file(GLOB_RECURSE CORE_SOURCES CONFIGURE_DEPENDS ${SRC}/src/*.cpp)
add_library(sts_core STATIC ${CORE_SOURCES})
target_include_directories(sts_core PUBLIC ${SRC}/include ${SRC}/bindings
                           ${CMAKE_CURRENT_SOURCE_DIR}/third_party)

pybind11_add_module(slaythespire ${SRC}/bindings/slaythespire.cpp ${SRC}/bindings/bindings-util.cpp)
target_link_libraries(slaythespire PRIVATE sts_core)

pybind11_add_module(fightsim ${AGENT}/fightsim.cpp)
target_include_directories(fightsim PRIVATE ${AGENT})
target_link_libraries(fightsim PRIVATE sts_core)

pybind11_add_module(live_combat_search ../steam/native/live_combat_search.cpp)
target_include_directories(live_combat_search PRIVATE ${AGENT})
target_link_libraries(live_combat_search PRIVATE sts_core)

if(NOT STS_RUNTIME_DIR)
  set(STS_RUNTIME_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../runtime)
endif()
set_target_properties(slaythespire fightsim live_combat_search PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY ${STS_RUNTIME_DIR}/engine)

include(CTest)
if(BUILD_TESTING)
  add_executable(thief_value_test tests/thief_value_test.cpp)
  target_link_libraries(thief_value_test PRIVATE sts_core)
  add_test(NAME thief_value COMMAND thief_value_test)
  add_executable(victory_hp_test combat4r/tools/victory_hp_contract.cpp)
  target_link_libraries(victory_hp_test PRIVATE sts_core)
  add_test(NAME victory_hp COMMAND victory_hp_test)
endif()
