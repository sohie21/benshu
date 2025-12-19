import { Tabs } from 'expo-router';
import React from 'react';

import { HapticTab } from '@/components/haptic-tab';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

export default function TabLayout() {
  const colorScheme = useColorScheme();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: Colors[colorScheme ?? 'light'].tint,
        headerShown: false,
        tabBarButton: HapticTab,
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'ЗАГРУЗИТЬ',
          tabBarIcon: ({ color, focused }) => <IconSymbol size={28} name={focused ? "square.and.arrow.up.fill":"square.and.arrow.up"} color={color} />,
        }}
      />
      <Tabs.Screen
        name="explore"
        options={{
          title: 'ЧИТАТЬ',
          tabBarIcon: ({ color, focused }) => <IconSymbol size={28} name={focused ? "book.fill":"book"} color={color} />,
        }}
      />
      <Tabs.Screen
        name="practice"
        options={{
          title: 'ПРАКТИКА',
          tabBarIcon: ({ color, focused }) => <IconSymbol size={28} name={focused ? "flame.fill":"flame"} color={color} />,
        }}
      />
      <Tabs.Screen
        name="dictionary"
        options={{
          title: 'СЛОВАРЬ',
          tabBarIcon: ({ color, focused }) => <IconSymbol size={28} name={focused ? "bookmark.fill":"bookmark"} color={color} />,
        }}
      />
    </Tabs>
  );
}
