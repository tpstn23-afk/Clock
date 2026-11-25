"""수제알람: reproducible Fossify Clock customization. Run from repository root."""
from pathlib import Path
import math, wave, struct, subprocess, tempfile, random
ROOT=Path("app/src/main")
K=ROOT/"kotlin/org/fossify/clock"
def change(path, old, new):
    p=Path(path)
    s=p.read_text(encoding="utf-8")
    if s.count(old)!=1:
        raise RuntimeError(f"{p}: expected exactly one matching anchor: {old[:80]}")
    p.write_text(s.replace(old,new,1), encoding="utf-8")

# Keep namespace and original scheduling/receiver infrastructure intact.
change("app/build.gradle.kts",'applicationId = project.property("APP_ID").toString()','applicationId = "kr.suje.alarm"')
for locale, old in [("values","Clock"),("values-ko","시계")]:
    change(ROOT/f"res/{locale}/strings.xml",f'<string name="app_launcher_name">{old}</string>','<string name="app_launcher_name">수제알람</string>')

# Ten original synthesized recordings; no extracted YouTube media.
raw=ROOT/"res/raw"
raw.mkdir(parents=True,exist_ok=True)
patterns=[
([523,659,784,1047],.24,"bell"),([440,554,659,554],.36,"soft"),
([330,494,660,880,660],.19,"arcade"),([784,587,784,988],.28,"bird"),
([262,392,523,659],.40,"soft"),([660,660,880,660],.19,"pulse"),
([392,523,784,1047,784],.22,"bell"),([294,440,587,440],.30,"arcade"),
([880,740,622,740],.23,"bird"),([392,494,587,698,880],.26,"pulse")]
rate=22050
for idx,(notes,duration,kind) in enumerate(patterns):
    samples=[]
    for _ in range(5):
        for f in notes:
            n=int(rate*duration)
            for i in range(n):
                t=i/rate
                envelope=min(1,t/.015)*min(1,(duration-t)/.06)
                freq=f*(1+.035*math.sin(2*math.pi*8*t)) if kind=="bird" else f
                phase=2*math.pi*freq*t
                y=math.sin(phase)
                if kind=="bell": y=.72*y+.18*math.sin(2.01*phase)+.1*math.sin(3.99*phase)
                if kind=="arcade": y=.72*y+.2*math.sin(3*phase)+.08*math.sin(5*phase)
                if kind=="pulse": y*=.65+.35*math.sin(2*math.pi*5*t)
                samples.append(int(22000*envelope*y))
            samples.extend([0]*int(rate*.045))
        samples.extend([0]*int(rate*.22))
    with tempfile.TemporaryDirectory() as tmp:
        wav=Path(tmp)/"tone.wav"
        with wave.open(str(wav),"wb") as w:
            w.setparams((1,2,rate,0,"NONE","not compressed"))
            w.writeframes(struct.pack("<"+"h"*len(samples),*samples))
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(wav),"-codec:a","libmp3lame","-b:a","64k",str(raw/f"suje_{idx}.mp3")],check=True)

# Use an install-local shuffle, changing daily and stable across snoozes.
helper=K/"helpers/SujeSounds.kt"
helper.write_text('''package org.fossify.clock.helpers

import android.content.Context
import android.net.Uri
import java.time.LocalDate
import kotlin.random.Random

object SujeSounds {
    const val RANDOM = "suje:daily"
    const val WEEK = "suje:week:"
    const val FIXED = "suje:tone:"
    val names = arrayOf("아침 종소리", "포근한 아침", "8비트 기상", "새소리풍", "느긋한 아침", "기상 신호", "반짝이는 종", "게임풍", "휘파람풍", "모닝 행진")
    fun resolve(context: Context, value: String): Uri {
        val date = LocalDate.now()
        val prefs = context.getSharedPreferences("suje_sounds", Context.MODE_PRIVATE)
        val seed = if (prefs.contains("seed")) prefs.getLong("seed", 0L) else Random.nextLong().also {
            prefs.edit().putLong("seed", it).apply()
        }
        val day = date.toEpochDay()
        val index = when {
            value == RANDOM -> (0..9).shuffled(Random(seed))[Math.floorMod(day, 10L).toInt()]
            value.startsWith(WEEK) -> value.removePrefix(WEEK).split(",").getOrNull(date.dayOfWeek.value - 1)?.toIntOrNull() ?: 0
            value.startsWith(FIXED) -> value.removePrefix(FIXED).toIntOrNull() ?: 0
            else -> return Uri.parse(value)
        }.coerceIn(0,9)
        return Uri.parse("android.resource://"+context.packageName+"/raw/suje_"+index)
    }
}
''',encoding="utf-8")
service=K/"services/AlarmService.kt"
change(service,'setDataSource(this@AlarmService, alarm.soundUri.toUri())','setDataSource(this@AlarmService, org.fossify.clock.helpers.SujeSounds.resolve(this@AlarmService, alarm.soundUri))')
# Fallback for a deleted file or broken URI; do not leave alarm silently playing.
change(service,'''                mediaPlayer = null
            }
        }

        if (alarm.vibrate)''','''                mediaPlayer = null
                try {
                    val fallback = android.media.RingtoneManager.getDefaultUri(android.media.RingtoneManager.TYPE_ALARM)
                    mediaPlayer = MediaPlayer().apply {
                        setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build())
                        setDataSource(this@AlarmService, fallback)
                        isLooping = true
                        prepare()
                        start()
                    }
                } catch (fallbackError: Exception) {
                    fallbackError.printStackTrace()
                    mediaPlayer?.release()
                    mediaPlayer = null
                }
            }
        }

        if (alarm.vibrate || (alarm.soundUri != SILENT && mediaPlayer == null))''')
# Default new alarms to daily random.
change(K/"extensions/Context.kt",'''        soundTitle = defaultAlarmSound.title,
        soundUri = defaultAlarmSound.uri,
        label = ""
    )''','''        soundTitle = "매일 랜덤 (10종)",
        soundUri = org.fossify.clock.helpers.SujeSounds.RANDOM,
        label = ""
    )''')

p=K/"dialogs/EditAlarmDialog.kt"
s=p.read_text(encoding="utf-8")
anchor='''            editAlarmSound.setOnClickListener {
                SelectAlarmSoundDialog('''
assert s.count(anchor)==1
s=s.replace(anchor,'''            editAlarmSound.setOnClickListener {
                val modes = arrayOf("매일 랜덤 (10종)", "요일별 알람음", "수제 알람음 선택", "기본음 / 내 MP3 / 무음")
                AlertDialog.Builder(activity).setTitle("알람음 선택").setItems(modes) { _, mode ->
                    when (mode) {
                        0 -> setSujeSound(modes[0], org.fossify.clock.helpers.SujeSounds.RANDOM)
                        1 -> chooseWeekSounds()
                        2 -> AlertDialog.Builder(activity).setTitle("수제 알람음")
                            .setItems(org.fossify.clock.helpers.SujeSounds.names) { _, i ->
                                setSujeSound(org.fossify.clock.helpers.SujeSounds.names[i], org.fossify.clock.helpers.SujeSounds.FIXED+i)
                            }.show()
                        3 -> showSystemSounds()
                    }
                }.show()
            }
            editAlarmVibrateIcon.setColorFilter(textColor)
''',1)
# move upstream picker block into a method; preserve callback for imported files
start=s.index("                    activity = activity,",s.index("editAlarmSound.setOnClickListener"))
end=s.index("            editAlarmVibrateIcon.setColorFilter(textColor)",start)
picker=s[start:end]
# original closing of click listener is the last nonempty line
picker=picker.rsplit("            }",1)[0]
s=s[:start]+s[end:]
s=s.replace("            editAlarmVibrateIcon.setColorFilter(textColor)\n            editAlarmVibrateIcon.setColorFilter(textColor)","            editAlarmVibrateIcon.setColorFilter(textColor)")
s=s.replace("root.context.getDefaultAlarmSound(RingtoneManager.TYPE_ALARM)","activity.getDefaultAlarmSound(RingtoneManager.TYPE_ALARM)")
methods='''    private fun setSujeSound(title: String, uri: String) {
        alarm.soundTitle = title
        alarm.soundUri = uri
        binding.editAlarmSound.text = title
    }

    private fun chooseWeekSounds() {
        val sounds = org.fossify.clock.helpers.SujeSounds
        val prior = alarm.soundUri.takeIf { it.startsWith(sounds.WEEK) }
            ?.removePrefix(sounds.WEEK)?.split(",")?.mapNotNull { it.toIntOrNull() }
        val selected = IntArray(7) { i -> prior?.getOrNull(i)?.coerceIn(0,9) ?: i }
        val days = arrayOf("월요일","화요일","수요일","목요일","금요일","토요일","일요일")
        val form = android.widget.LinearLayout(activity).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(32, 16, 32, 16)
        }
        days.forEachIndexed { day, title ->
            form.addView(android.widget.TextView(activity).apply { text = title })
            form.addView(android.widget.Spinner(activity).apply {
                adapter = android.widget.ArrayAdapter(activity, android.R.layout.simple_spinner_dropdown_item, sounds.names)
                setSelection(selected[day])
            })
        }
        val scroll = android.widget.ScrollView(activity).apply { addView(form) }
        AlertDialog.Builder(activity).setTitle("요일별 알람음").setView(scroll)
            .setPositiveButton("저장") { _, _ ->
                for (i in 0..6) selected[i] = (form.getChildAt(i*2+1) as android.widget.Spinner).selectedItemPosition
                setSujeSound("요일별 알람음", sounds.WEEK + selected.joinToString(","))
            }.setNegativeButton("취소", null).show()
    }

    private fun showSystemSounds() {
        SelectAlarmSoundDialog(
'''+picker.replace("root.context.getDefaultAlarmSound","activity.getDefaultAlarmSound")+'''    }

'''
s=s.replace("    private fun restoreLastAlarm() {",methods+"    private fun restoreLastAlarm() {",1)
p.write_text(s,encoding="utf-8")

# Alarm-only launcher UI: retain internal classes for compatibility.
main=K/"activities/MainActivity.kt"
change(main,"        setupTabs()\n        updateWidgets()","        setupTabs()\n        binding.mainTabsHolder.visibility = android.view.View.GONE\n        updateWidgets()")
change(main,"        checkShortcuts()","        // No stopwatch shortcut in Suje Alarm.")
change(main,"        binding.viewPager.currentItem = getTabIndex(tabToOpen)","        binding.viewPager.currentItem = TAB_ALARM_INDEX")
change(main,'''            binding.mainTabsHolder.getTabAt(it)?.select()
            refreshMenuItems()''','''            if (it != TAB_ALARM_INDEX) {
                binding.viewPager.setCurrentItem(TAB_ALARM_INDEX, false)
            } else {
                binding.mainTabsHolder.getTabAt(it)?.select()
                refreshMenuItems()
            }''')
change(main,"binding.viewPager.setCurrentItem(getTabIndex(tabToOpen), false)","binding.viewPager.setCurrentItem(TAB_ALARM_INDEX, false)")

# Replace swipe UI with two large buttons and a custom cheerful sunrise.
p=K/"activities/AlarmActivity.kt"
s=p.read_text(encoding="utf-8")
start=s.index('    @SuppressLint("ClickableViewAccessibility")')
end=s.index("    override fun onConfigurationChanged",start)
s=s[:start]+'''    private var showingWeather = false

    private fun setupAlarmButtons() {
        binding.reminderDismiss.setOnClickListener { dismissAlarmAndFinish() }
        binding.reminderSnooze.setOnClickListener { snoozeAlarm() }
    }

'''+s[end:]
s=s.replace('''                alarmController.stopAlarm(alarm!!.id)
            }
        }

        finishActivity()''','''                showingWeather = true
                alarmController.stopAlarm(alarm!!.id)
                showMorningWeather()
                return
            }
        }

        finishActivity()''')
s=s.replace("if (event.alarmId == alarm?.id && !isFinishing)","if (event.alarmId == alarm?.id && !isFinishing && !showingWeather)")
s=s.replace("    private fun showOverLockscreen() {",'''    private fun showMorningWeather() {
        binding.reminderDismiss.isEnabled = false
        binding.reminderSnooze.visibility = android.view.View.GONE
        binding.reminderTitle.text = "좋은 아침입니다!"
        binding.reminderText.text = "서울 날씨 확인 중…"
        binding.reminderDismiss.text = "닫기"
        binding.reminderDismiss.setOnClickListener { finishActivity() }
        binding.reminderDismiss.isEnabled = true
        Thread {
            val weather = try {
                val url = java.net.URL("https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.9780&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FSeoul&forecast_days=1")
                val connection = url.openConnection().apply { connectTimeout = 4000; readTimeout = 4000 }
                val json = org.json.JSONObject(connection.getInputStream().bufferedReader().use { it.readText() })
                val current = json.getJSONObject("current")
                val daily = json.getJSONObject("daily")
                val code = current.getInt("weather_code")
                val condition = when (code) {
                    0 -> "맑음"
                    in 1..3 -> "구름"
                    in 45..48 -> "안개"
                    in 51..67, in 80..82 -> "비"
                    in 71..77, in 85..86 -> "눈"
                    in 95..99 -> "뇌우"
                    else -> "날씨 확인"
                }
                "서울  " + condition + "  " + current.getDouble("temperature_2m") + "°C\\\\n최저 " +
                    daily.getJSONArray("temperature_2m_min").getDouble(0) + "°  /  최고 " +
                    daily.getJSONArray("temperature_2m_max").getDouble(0) + "°"
            } catch (e: Exception) { "날씨를 불러오지 못했습니다." }
            runOnUiThread { if (!isFinishing && !isDestroyed) binding.reminderText.text = weather }
        }.start()
    }

    private fun showOverLockscreen() {'''.replace("\\\\n","\\n"))
p.write_text(s,encoding="utf-8")
(ROOT/"res/layout/activity_alarm.xml").write_text('''<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:id="@+id/reminder_holder" android:layout_width="match_parent" android:layout_height="match_parent"
    android:orientation="vertical" android:gravity="center" android:padding="24dp" android:background="#FFF1D8">
    <TextView android:layout_width="180dp" android:layout_height="180dp" android:gravity="center"
        android:text="☀" android:textColor="#EE8B38" android:textSize="112sp" android:contentDescription="해님"/>
    <TextView android:id="@+id/reminder_title" android:layout_width="match_parent" android:layout_height="wrap_content"
        android:gravity="center" android:textColor="#513D33" android:textSize="24sp" android:textStyle="bold"/>
    <TextView android:id="@+id/reminder_text" android:layout_width="match_parent" android:layout_height="wrap_content"
        android:gravity="center" android:padding="20dp" android:textColor="#513D33" android:textSize="36sp"/>
    <Button android:id="@+id/reminder_dismiss" android:layout_width="match_parent" android:layout_height="64dp"
        android:layout_marginTop="24dp" android:text="일어났어요!" android:textSize="20sp" android:textColor="#FFFFFF"
        android:backgroundTint="#CA683E"/>
    <Button android:id="@+id/reminder_snooze" android:layout_width="match_parent" android:layout_height="60dp"
        android:layout_marginTop="12dp" android:text="조금만 더 잘래요" android:textSize="17sp" android:textColor="#513D33"
        android:backgroundTint="#F8D99E"/>
</LinearLayout>
''',encoding="utf-8")
# Internet used solely for the post-dismiss Seoul forecast.
change(ROOT/"AndroidManifest.xml",'    <uses-permission android:name="android.permission.VIBRATE" />','    <uses-permission android:name="android.permission.INTERNET" />\n    <uses-permission android:name="android.permission.VIBRATE" />')
print("Suje Alarm customization applied.")
