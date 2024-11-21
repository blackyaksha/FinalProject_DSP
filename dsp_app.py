import streamlit as st
import tensorflow as tf
import numpy as np
import cv2
from PIL import Image, ImageOps
import editdistance
import pytesseract
import os
import pickle

@st.cache_resource
def load_model():
    # Update this path to point to where your 'autoencoder.h5' file is located  
    model = tf.keras.models.load_model('autoencoder.h5')
    return model

model = load_model()

st.write("""
# Text Detection and Extraction
### By Tacsay & Yu
""")

truth = st.text_input('Actual Text')

file = st.file_uploader("Choose document image", type=["jpg", "png"])

def denoise(image):
    size = (612, 360)
    img = ImageOps.fit(image, size)
    img = img.convert('L')
    img = np.array(img).reshape((360, 612, 1))  # Reshape to add channel dimension
    img = img / 255.0  # Normalize
    img_array = np.expand_dims(img, axis=0)
    denoised = model.predict(img_array)
    denoised_image_array = denoised.squeeze(axis=(0, 3))  # Remove singleton dimensions
    return denoised_image_array

def rectify(h):
    h = h.reshape((4, 2))
    hnew = np.zeros((4, 2), dtype=np.float32)
    add = h.sum(1)
    hnew[0] = h[np.argmin(add)]
    hnew[2] = h[np.argmax(add)]
    diff = np.diff(h, axis=1)
    hnew[1] = h[np.argmin(diff)]
    hnew[3] = h[np.argmax(diff)]
    return hnew

def resize_image(image, width, height):
    image = cv2.resize(image, (width, height))
    return image

def gray_image(image):
    if len(image.shape) == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image

def canny_edge_detection(image):
    blurred_image = cv2.GaussianBlur(image, (5, 5), 0)
    edges = cv2.Canny(blurred_image, 0, 50)
    return edges

def find_contours(image):
    contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    for c in contours:
        p = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * p, True)
        if len(approx) == 4:
            return approx
    return None

def draw_contours(orig_image, image, target):
    approx = rectify(target)
    pts2 = np.float32([[0, 0], [800, 0], [800, 800], [0, 800]])

    M = cv2.getPerspectiveTransform(approx, pts2)
    cv2.drawContours(image, [target], -1, (0, 255, 0), 2)
    result = image
    return result

def calculate_wer(predicted, ground_truth):
    if not isinstance(predicted, str) or not isinstance(ground_truth, str):
        raise ValueError("Both predicted and ground_truth must be strings.")
    predicted_words = predicted.split()
    ground_truth_words = ground_truth.split()
    if len(ground_truth_words) == 0:
        raise ValueError("The ground_truth string must contain at least one word.")
    wer = editdistance.eval(predicted_words, ground_truth_words) / len(ground_truth_words)
    accuracy = 1 - wer
    return wer * 100, accuracy * 100  # Convert to percentage

def calculate_cer(predicted, ground_truth):
    if not isinstance(predicted, str) or not isinstance(ground_truth, str):
        raise ValueError("Both predicted and ground_truth must be strings.")
    if len(ground_truth) == 0:
        raise ValueError("The ground_truth string must not be empty.")
    cer = editdistance.eval(predicted, ground_truth) / len(ground_truth)
    accuracy = 1 - cer
    return cer * 100, accuracy * 100  # Convert to percentage

if st.button("Process"):
    if file is None:
        st.text("Please upload an image file")
    else:
        image = Image.open(file)
        st.image(image, use_column_width=True)

        # Denoise the image
        denoised_image_array = denoise(image)

        # Convert denoised image to uint8 for display
        denoised_image_uint8 = (denoised_image_array * 255).astype('uint8')

        # Display denoised image in Streamlit
        st.image(denoised_image_uint8, caption="Denoised Image", use_column_width=True)

        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        sharpened_image = cv2.filter2D(denoised_image_uint8, -1, kernel)

        scale_percent = 150
        width = int(sharpened_image.shape[1] * (scale_percent / 100))
        height = int(sharpened_image.shape[0] * (scale_percent / 100))

        resized_image = cv2.resize(sharpened_image, (width, height), interpolation=cv2.INTER_LINEAR)

        _, im_bw = cv2.threshold(resized_image, 185, 255, cv2.THRESH_BINARY)
        edges = canny_edge_detection(im_bw)

        target1 = find_contours(edges)
        if target1 is not None:
            output = draw_contours(resized_image, sharpened_image, target1)
            text = pytesseract.image_to_string(output)
            wer_calc, accuracy_wer = calculate_wer(text, truth)
            cer_calc, accuracy_cer = calculate_cer(text, truth)

            text_data = pytesseract.image_to_data(output, output_type='data.frame')
            text_data = text_data[text_data.conf != -1]

            lines = text_data.groupby(['page_num', 'block_num', 'par_num', 'line_num'])['text'].apply(lambda x: ' '.join(list(x))).tolist()
            confs = text_data.groupby(['page_num', 'block_num', 'par_num', 'line_num'])['conf'].mean().tolist()
            line_conf = []

            total_conf = sum(confs)
            num_values = len(confs)
            average_conf = round(total_conf / num_values, 2) if num_values != 0 else 0

            for i in range(len(lines)):
                if lines[i].strip():
                    line_conf.append((lines[i], round(confs[i], 3)))

            string = f"Detected Text:\n{text}\n\nWER Accuracy: {accuracy_wer:.2f}% | CER Accuracy: {accuracy_cer:.2f}%"
            st.success(string)
