// A release build is a windowed application with no console window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    comodor_desktop::run();
}
