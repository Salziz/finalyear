import cv2
import os

PERSON_NAME = "Salim Abdulaziz"
LABEL = 4  # must match face_encoding_label you used in the database
SAVE_DIR = f"static/captures/seed/salim_samples"
os.makedirs(SAVE_DIR, exist_ok=True)

cam = cv2.VideoCapture(0)
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
count = 0

print(f"Enrolling {PERSON_NAME} — capturing 30 samples.")
print("Look at the camera. Slightly move your head around.")

while count < 30:
    ret, frame = cam.read()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)
    for (x, y, w, h) in faces:
        count += 1
        face_img = gray[y:y+h, x:x+w]
        cv2.imwrite(f"{SAVE_DIR}/{count}.jpg", face_img)
        cv2.rectangle(frame, (x,y), (x+w, y+h), (0,255,0), 2)
        cv2.putText(frame, f"Sample {count}/30", (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
    cv2.imshow("Enrolling - press Q to quit", frame)
    if cv2.waitKey(100) & 0xFF == ord('q'):
        break

cam.release()
cv2.destroyAllWindows()
print(f"Done. {count} samples saved to {SAVE_DIR}")